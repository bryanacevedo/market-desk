"""The four AI tasks and their gates. The model returns structure; code checks it. On a failed gate the task gets one
rewrite with the failures; a second failure withholds the output, and the screen shows figures without words."""
from __future__ import annotations

import re

from . import catalog as C
from . import llm

NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?[%kKmM]?")
QUOTED = re.compile(r"[\"“]([^\"”]{3,})[\"”]")
LINK = re.compile(r"(https?://|www\.|\b[\w-]+\.(com|io|net|org|example)\b|@)", re.I)
NEED = re.compile(r"\b(the buyer needs|buyers need|they need|you need|needs to)\b", re.I)


def numbers(text: str) -> set[str]:
    return {m.group(0).rstrip(".,").lower() for m in NUM.finditer(text)}


# ---------------------------------------------------------------- classify

def classify_payload(name: str, description: str) -> dict:
    return {"company": {"name": name, "description": llm.wrap_data(description)}, "industries": C.INDUSTRIES,
            "pricing_models": C.PRICING}


def classify_gate(description: str, out: dict) -> list[str]:
    fails = []
    for label, quote, allowed in (("industry", "industry_quote", C.INDUSTRIES), ("pricing_model", "pricing_quote", C.PRICING)):
        v = out.get(label)
        if v != "unknown" and v not in allowed:
            fails.append(f"{label} '{v}' is not in the list")
        elif v != "unknown":
            q = (out.get(quote) or "").strip()
            if not q:
                fails.append(f"{label} has no quote")
            elif q not in description:
                fails.append(f"{label} quote is not copied exactly from the description")
    return fails


def classify(cur, name: str, description: str, ask=None) -> dict | None:
    ask = ask or (lambda t, p: llm.run(cur, t, p))
    payload = classify_payload(name, description)
    for _attempt in range(2):
        out = ask("classify", payload)
        fails = classify_gate(description, out)
        if not fails:
            return out
        payload = {**payload, "failures": fails}
    return None


# ---------------------------------------------------------------- loss_code

def loss_payload(text: str, kind: str = "loss") -> dict:
    return {"kind": kind, "text": llm.wrap_data(text), "competitors": C.COMPETITORS}


def loss_gate(text: str, out: dict) -> dict:
    """A competitor counts only if it is in the list and its name is in the text; otherwise it is cleared."""
    comp = out.get("competitor")
    if comp and (comp not in C.COMPETITORS or comp.lower() not in text.lower()):
        out = {**out, "competitor": None}
    if out.get("code") not in C.LOSS_CODES:
        out = {**out, "code": "other"}
    return out


def code_loss(cur, text: str, kind: str = "loss", ask=None) -> dict:
    ask = ask or (lambda t, p: llm.run(cur, t, p))
    return loss_gate(text, ask("loss_code", loss_payload(text, kind)))


# ---------------------------------------------------------------- segment_story

def story_gate(payload: dict, out: dict, forbidden: list[str]) -> list[str]:
    fails = []
    quotes = {q["id"]: q["text"] for q in payload["quotes"]}
    allowed = set()
    for f in payload["figures"]:
        allowed |= numbers(str(f["value"]))
    sents = out.get("sentences") or []
    if not 1 <= len(sents) <= 4:
        fails.append(f"{len(sents)} sentences; write one to four")
    for i, s in enumerate(sents):
        ids = s.get("quote_ids") or []
        if not ids:
            fails.append(f"sentence {i + 1} cites no quote")
        bad = [q for q in ids if q not in quotes]
        if bad:
            fails.append(f"sentence {i + 1} cites quote ids that were not given: {bad}")
        cited = " ".join(quotes.get(q, "") for q in ids)
        for m in QUOTED.finditer(s["text"]):
            if m.group(1).strip() not in cited:
                fails.append(f"sentence {i + 1} quotes words that are not in its cited quotes")
        extra = numbers(s["text"]) - allowed
        if extra:
            fails.append(f"sentence {i + 1} has numbers that are not figures given: {sorted(extra)}")
        for name in forbidden:
            if name and re.search(rf"\b{re.escape(name)}\b", s["text"], re.I):
                fails.append(f"sentence {i + 1} names {name}")
        if LINK.search(s["text"]):
            fails.append(f"sentence {i + 1} has a link or an address")
    return fails


def segment_story(cur, payload: dict, forbidden: list[str], ask=None) -> tuple[list[dict] | None, list[str]]:
    ask = ask or (lambda t, p: llm.run(cur, t, p))
    p = payload
    fails: list[str] = []
    for _attempt in range(2):
        out = ask("segment_story", p)
        fails = story_gate(payload, out, forbidden)
        if not fails:
            return out["sentences"], []
        p = {**payload, "failures": fails}
    return None, fails


# ---------------------------------------------------------------- proposal_text

VOCAB = sorted({*C.INDUSTRIES, *[b[0] for b in C.SIZE_BANDS], *C.PRICING_LABEL.values(), *C.TECH, *C.REVENUE_BANDS,
                "North America", "Europe", "Latin America", "Asia Pacific", *C.COUNTRY_NAME.values()} - {"Unknown", "Mixed"},
               key=len, reverse=True)


def proposal_gate(payload: dict, out: dict) -> list[str]:
    fails = []
    ch = payload["change"]
    d = out.get("describes") or {}
    if (d.get("kind"), d.get("field"), d.get("value_label")) != (ch["kind"], ch["field"], ch["value_label"]):
        fails.append("describes does not match the change given")
    sents = out.get("sentences") or []
    if len(sents) != 2:
        fails.append(f"{len(sents)} sentences; write exactly two")
    text = " ".join(s["text"] for s in sents)
    if ch["value_label"].lower() not in text.lower():
        fails.append(f"the text does not name {ch['value_label']}")
    given = {f["id"]: f for f in payload["findings"]}
    mentioned = {ch["value_label"].lower(), ch.get("field_label", "").lower()}
    for f in payload["findings"]:
        mentioned |= {str(f.get("value", "")).lower(), str(f.get("trait", "")).lower()}
    for i, s in enumerate(sents):
        ids = s.get("finding_ids") or []
        if any(x not in given for x in ids):
            fails.append(f"sentence {i + 1} cites findings that were not given")
        allowed = numbers(str(ch.get("weight") or "")) | numbers(ch["value_label"])
        for x in ids or list(given):
            f = given.get(x) or {}
            for k in ("opportunities", "win_rate", "range", "rest_win_rate", "top_loss", "value"):
                allowed |= numbers(str(f.get(k) or ""))
        extra = numbers(s["text"]) - allowed
        if extra:
            fails.append(f"sentence {i + 1} has numbers that are not figures of its findings: {sorted(extra)}")
    low = text.lower()
    for term in VOCAB:
        t = term.lower()
        if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", low) and not any(t in m or m in t for m in mentioned if m):
            fails.append(f"names {term}, which is not in the findings")
            low = low.replace(t, " ")
    if NEED.search(text):
        fails.append("says what someone needs")
    if LINK.search(text):
        fails.append("has a link or an address")
    return fails


def proposal_text(cur, payload: dict, ask=None) -> tuple[list[dict] | None, list[str]]:
    ask = ask or (lambda t, p: llm.run(cur, t, p))
    p = payload
    fails: list[str] = []
    for _attempt in range(2):
        out = ask("proposal_text", p)
        fails = proposal_gate(payload, out)
        if not fails:
            return out["sentences"], []
        p = {**payload, "failures": fails}
    return None, fails
