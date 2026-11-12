"""Deterministic stand-ins for the four AI tasks, used by the demo and the tests when no recording matches. They are
written in code, labelled as simulated, and kept simple: they exercise the gates, they do not imitate the model's
judgment. The segment story stand-in writes a figure it was not given for the Enterprise segment, on purpose, so the
withheld state is exercised (README, "What is real and what is simulated")."""
from __future__ import annotations

import re

from . import catalog as C
from .llm import sim
from .sim.world import INDUSTRY_PHRASE, PRICING_PHRASE


def _unwrap(text: str) -> str:
    return text.removeprefix("<data>").removesuffix("</data>")


@sim("classify")
def _classify(p: dict) -> dict:
    desc = _unwrap(p["company"]["description"])
    out = {"industry": "unknown", "industry_quote": None, "pricing_model": "unknown", "pricing_quote": None,
           "instructions_in_text": bool(re.search(r"ignore (all |previous )?instructions", desc, re.I))}
    for ind, phrase in INDUSTRY_PHRASE.items():
        if phrase in desc:
            out["industry"], out["industry_quote"] = ind, phrase
            break
    for pm, phrase in PRICING_PHRASE.items():
        if phrase in desc:
            out["pricing_model"], out["pricing_quote"] = pm, phrase
            break
    return out


KEYWORDS = [
    ("compliance", r"hipaa|security|infosec|compliance|soc 2|residency|phi|hitrust|gdpr"),
    ("competitor", r"went with|chose|lost to|picked|moved to|consolidated onto|already in their stack"),
    ("champion_left", r"champion|resigned|moved on|new cfo|laid off|left the company"),
    ("price", r"price|pricing|expensive|budget|cost|% off"),
    ("timing", r"timing|quarter|next fy|revisit|after q\d|reorg|migration first"),
    ("missing_feature", r"needs? |connector|no native|missing|wanted|outgrew|module"),
    ("bad_fit", r"too small|not a fit|bill hours|no need|flat|no longer needed|pivot"),
    ("no_decision", r"dark|ghost|no decision|status quo|committee|never got"),
]


@sim("loss_code")
def _loss(p: dict) -> dict:
    text = _unwrap(p["text"]).lower()
    code = next((c for c, rx in KEYWORDS if re.search(rx, text)), "other")
    comp = next((c for c in p["competitors"] if c.lower() in text), None)
    return {"code": code, "competitor": comp if code == "competitor" else None}


@sim("segment_story")
def _story(p: dict) -> dict:
    figs = {f["id"]: f for f in p["figures"]}
    by_kind: dict[str, list[dict]] = {}
    for q in p["quotes"]:
        by_kind.setdefault(q["kind"], []).append(q)
    out = []
    if by_kind.get("reason_to_buy"):
        q = by_kind["reason_to_buy"][0]
        f = figs.get("win_rate")
        out.append({"text": f"Buyers here say \"{q['text']}\"" + (f", and they win at {f['value']}." if f else "."),
                    "quote_ids": [q["id"]], "figure_ids": ["win_rate"] if f else []})
    if by_kind.get("objection"):
        q = by_kind["objection"][0]
        out.append({"text": f"The common objection is \"{q['text']}\".", "quote_ids": [q["id"]], "figure_ids": []})
    if by_kind.get("competitor"):
        q = by_kind["competitor"][0]
        out.append({"text": f"Competitors come up: \"{q['text']}\".", "quote_ids": [q["id"]], "figure_ids": []})
    signer = figs.get("signer")
    if signer and out:
        out.append({"text": f"The {signer['value'].lower()} signs most deals.", "quote_ids": out[0]["quote_ids"],
                    "figure_ids": ["signer"]})
    if p["segment"]["key"] == "enterprise" and out:
        out[0]["text"] = out[0]["text"].rstrip(".") + ", and deals take 200 days."
    return {"sentences": out[:4]}


@sim("proposal_text")
def _proposal(p: dict) -> dict:
    ch, fs = p["change"], p["findings"]
    f = fs[0] if fs else None
    verb = {"add_rule": "Add a rule for", "drop_rule": "Drop the rule on", "penalty": "Lower the score of",
            "add_exclude": "Exclude", "reweight": "Reweight the rule on", "segment_expand": "Add weight for"}.get(ch["kind"], "Change")
    first = f"{verb} {ch['field_label'].lower()}: {ch['value_label']}."
    second = (f"{f['value']} won {f['win_rate']} of {f['opportunities']} opportunities, against {f['rest_win_rate']} for the rest."
              if f else "The deals behind it are in the findings.")
    if f and f.get("top_loss") and ch["kind"] == "add_exclude":
        second = second.rstrip(".") + f"; the most common loss was {f['top_loss']}."
    return {"describes": {"kind": ch["kind"], "field": ch["field"], "value_label": ch["value_label"]},
            "sentences": [{"text": first, "finding_ids": [f["id"]] if f else []},
                          {"text": second, "finding_ids": [f["id"]] if f else []}]}


@sim("judge")
def _judge(p: dict) -> dict:
    return {"faithful": True, "problems": []}


_ = C
