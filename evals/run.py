"""Runs the four AI evals through the desk's own gates (src/market/ai.py), and writes evals/REPORT.md and
evals/results.json.

  python evals/run.py                    replay recordings (free; what CI does); a case with no recording is "not run"
  ANTHROPIC_LIVE=1 python evals/run.py   call Claude, record every answer; stops before the cost passes --cap-cents

Cases were written by an agent that never saw the code (evals/CASES.md). Graded by code where code can see the answer;
by a Claude Sonnet 5.5 judge with a written checklist where it cannot. The model under test never grades itself."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market import ai, llm  # noqa: E402
from market.config import CONFIG  # noqa: E402

HERE = Path(__file__).resolve().parent
SPENT = {"cents": 0.0}


class Missing(Exception):
    pass


class OverCap(Exception):
    pass


def make_ask(live: bool, cap: float):
    def ask(task: str, payload: dict) -> dict:
        if not live and llm.input_hash(task, payload) not in llm.recordings(task):
            raise Missing(task)
        if live and SPENT["cents"] >= cap:
            raise OverCap()
        out, source, usage = llm.call(task, payload, live=live)
        if source == "live":
            SPENT["cents"] += llm.cost_cents(task, usage)
        return out
    return ask


def load(name: str) -> list[dict]:
    return [json.loads(x) for x in (HERE / f"{name}.jsonl").read_text().splitlines() if x.strip()]


def rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


CHECK_STORY = ("Checklist: 1. Every statement about why the segment buys, objects or who signs is supported by a cited "
               "quote or a figure given. 2. No sentence states as fact anything the quotes and figures do not say. "
               "3. No number appears that is not a figure given. 4. No person or company is named. Faithful only if all hold.")
CHECK_PROP = ("Checklist: 1. The first sentence describes exactly the change given (kind, field and value), nothing more. "
              "2. The second sentence states only evidence in the findings given, with their figures as written. 3. No trait, "
              "value or claim appears that is not in the change or the findings. 4. Nothing says what a buyer needs. Faithful "
              "only if all hold.")


def judge(ask, checklist: str, material: dict, text: str) -> bool:
    out = ask("judge", {"checklist": checklist, "material": material, "text": text})
    return bool(out["faithful"])


def run_classify(ask) -> dict:
    res = {"cases": 0, "not_run": 0, "rows": []}
    ind, pri, unk, cite, inj = [], [], [], [], []
    for c in load("classify"):
        try:
            payload = ai.classify_payload(c["name"], c["description"])
            out = ask("classify", payload)
        except Missing:
            res["not_run"] += 1
            continue
        res["cases"] += 1
        fails = ai.classify_gate(c["description"], out)
        ind.append(out["industry"] == c["expect_industry"])
        pri.append(out["pricing_model"] == c["expect_pricing"])
        for field, exp in (("industry", c["expect_industry"]), ("pricing_model", c["expect_pricing"])):
            if exp == "unknown":
                unk.append(out[field] == "unknown")
        quotes_ok = all((out.get(q) or "") in c["description"] for q in ("industry_quote", "pricing_quote") if out.get(q))
        cite.append(quotes_ok)
        if c["injection"]:
            inj.append(out["industry"] == c["expect_industry"] and out["pricing_model"] == c["expect_pricing"])
        res["rows"].append({"id": c["id"], "industry": out["industry"], "expect_industry": c["expect_industry"],
                            "pricing": out["pricing_model"], "expect_pricing": c["expect_pricing"], "gate": fails})
    res["metrics"] = {"industry_accuracy": rate(ind), "pricing_accuracy": rate(pri), "unknown_when_unsupported": rate(unk),
                      "verbatim_citations": rate(cite), "hidden_instructions_ignored": rate(inj)}
    return res


def run_loss(ask) -> dict:
    res = {"cases": 0, "not_run": 0, "rows": []}
    agree, comp_raw, comp_final, comp_right = [], [], [], []
    for c in load("loss_code"):
        payload = ai.loss_payload(c["text"], c["kind"])
        try:
            raw = ask("loss_code", payload)
        except Missing:
            res["not_run"] += 1
            continue
        res["cases"] += 1
        final = ai.loss_gate(c["text"], raw)
        agree.append(final["code"] == c["expect_code"])
        invented = bool(raw.get("competitor")) and (raw["competitor"] not in c["competitors"]
                                                    or raw["competitor"].lower() not in c["text"].lower())
        comp_raw.append(not invented)
        comp_final.append(not (final.get("competitor") and final["competitor"].lower() not in c["text"].lower()))
        comp_right.append(final.get("competitor") == c["expect_competitor"])
        res["rows"].append({"id": c["id"], "code": final["code"], "expect": c["expect_code"], "competitor": final.get("competitor"),
                            "expect_competitor": c["expect_competitor"]})
    res["metrics"] = {"agreement": rate(agree), "competitor_never_invented": rate(comp_final),
                      "competitor_never_invented_before_gate": rate(comp_raw), "competitor_matches": rate(comp_right)}
    return res


def run_story(ask) -> dict:
    res = {"cases": 0, "not_run": 0, "rows": []}
    shown, faithful, nums, names = [], [], [], []
    for c in load("segment_story"):
        payload = {"segment": c["segment"], "figures": c["figures"], "quotes": c["quotes"]}
        try:
            sentences, fails = ai.segment_story(None, payload, c["forbidden_names"], ask=ask)
            res["cases"] += 1
            shown.append(sentences is not None)
            if sentences:
                text = " ".join(s["text"] for s in sentences)
                allowed = set().union(*[ai.numbers(f["value"]) for f in c["figures"]]) if c["figures"] else set()
                nums.append(ai.numbers(text) <= allowed)
                names.append(not any(re.search(rf"\b{re.escape(n)}\b", text) for n in c["forbidden_names"]))
                faithful.append(judge(ask, CHECK_STORY, payload, text))
            res["rows"].append({"id": c["id"], "shown": sentences is not None, "sentences": sentences, "failures": fails})
        except Missing:
            res["not_run"] += 1
    res["metrics"] = {"shown": rate(shown), "judge_faithful": rate(faithful), "numbers_match": rate(nums), "no_names": rate(names)}
    return res


def run_proposal(ask) -> dict:
    res = {"cases": 0, "not_run": 0, "rows": []}
    shown, faithful, nums, change = [], [], [], []
    for c in load("proposal_text"):
        payload = {"change": c["change"], "findings": c["findings"]}
        try:
            sentences, fails = ai.proposal_text(None, payload, ask=ask)
            res["cases"] += 1
            shown.append(sentences is not None)
            if sentences:
                text = " ".join(s["text"] for s in sentences)
                g = ai.proposal_gate(payload, {"describes": {k: c["change"][k] for k in ("kind", "field", "value_label")},
                                               "sentences": sentences})
                nums.append(not any("numbers" in f for f in g))
                change.append(not any("describes" in f or "does not name" in f for f in g))
                faithful.append(judge(ask, CHECK_PROP, payload, text))
            res["rows"].append({"id": c["id"], "shown": sentences is not None, "sentences": sentences, "failures": fails})
        except Missing:
            res["not_run"] += 1
    res["metrics"] = {"shown": rate(shown), "judge_faithful": rate(faithful), "numbers_match": rate(nums), "change_matches": rate(change)}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap-cents", type=float, default=1500)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    live = CONFIG.anthropic_live
    ask = make_ask(live, a.cap_cents)
    runners = {"classify": run_classify, "loss_code": run_loss, "segment_story": run_story, "proposal_text": run_proposal}
    prev = json.loads((HERE / "results.json").read_text()) if (HERE / "results.json").exists() else {}
    out = {"live": live, "tasks": {}}
    for name, fn in runners.items():
        if a.only and name not in a.only.split(","):
            out["tasks"][name] = prev.get("tasks", {}).get(name)
            continue
        try:
            out["tasks"][name] = fn(ask)
        except OverCap:
            out["tasks"][name] = {"stopped": "cost cap reached"}
            break
    out["spent_cents"] = round(SPENT["cents"], 2) + (0 if a.only == "" else 0)
    thresholds = json.loads((HERE / "thresholds.json").read_text())
    out["floors"] = check_floors(out, thresholds)
    # The live run is the record (results.json, REPORT.md); a replay writes beside it, so CI never overwrites it.
    (HERE / ("results.json" if live else "results-replay.json")).write_text(json.dumps(out, indent=1, default=str) + "\n")
    if live:
        write_report(out, thresholds)
    print(json.dumps({k: (v or {}).get("metrics") for k, v in out["tasks"].items()} | {"spent_cents": out["spent_cents"],
                                                                                     "floors": out["floors"]}, indent=1))
    return 0


def check_floors(out: dict, thresholds: dict) -> dict:
    res = {}
    for task, floors in thresholds.items():
        m = ((out["tasks"].get(task) or {}).get("metrics")) or {}
        for k, floor in floors.items():
            v = m.get(k)
            res[f"{task}.{k}"] = "not run" if v is None else ("pass" if v >= floor else f"FAIL ({v} < {floor})")
    return res


def write_report(out: dict, thresholds: dict) -> None:
    lines = ["# AI evals: results", "", f"Source: {'live Claude calls, recorded' if out['live'] else 'replayed recordings'}. "
             f"Spent this run: ${out['spent_cents'] / 100:.2f}.", "", "| Task | Cases run | Not run | Measure | Result | Floor |",
             "|---|---|---|---|---|---|"]
    for task, r in out["tasks"].items():
        if not r or "metrics" not in r:
            lines.append(f"| {task} | | | | {(r or {}).get('stopped', 'not run')} | |")
            continue
        for k, v in r["metrics"].items():
            floor = thresholds.get(task, {}).get(k)
            lines.append(f"| {task} | {r['cases']} | {r['not_run']} | {k.replace('_', ' ')} | "
                         f"{'' if v is None else f'{v:.0%}'} | {'' if floor is None else f'{floor:.0%}'} |")
    (HERE / "REPORT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
