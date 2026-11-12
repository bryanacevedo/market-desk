"""Call-note redaction at import. A prospect's name never reaches the database: names from the CRM contact list
become the person's role in brackets, then a name-pattern pass catches titles and capitalised first-and-last-name
pairs that the contact list missed. The original text is never stored.

Known limit: a name written all in lower case, not in the CRM contact list and not a common first name, is not caught
(README, "Not yet proven")."""
from __future__ import annotations

import re

from .sim.names import FIRST

_TITLE = re.compile(r"\b(?:mr|ms|mrs|dr|prof)\.?\s+[^\W\d_][\w'\-]+(?:\s+(?-i:[A-Z])[\w'\-]+)?", re.I)
# Initials and a surname: "M. Klein", "J. R. Tanaka".
_INITIALS = re.compile(r"\b(?:[A-Z]\.\s*){1,3}[A-Z][\w'\-]+")
# Words in a script other than Latin (Cyrillic, Greek, CJK, Arabic, Hebrew and others): call notes here are written in
# English, so such a word is taken as a name.
_NON_LATIN = re.compile(r"[\u0370-\u03ff\u0400-\u052f\u0590-\u06ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+(?:\s+[\u0370-\u03ff\u0400-\u052f\u0590-\u06ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+)*")
_PROFILE = re.compile(r"\b(?:https?://)?(?:[\w-]+\.)?(?:linkedin\.com|x\.com|twitter\.com)/\S+", re.I)
# A capitalised word after a word that introduces a person: "Spoke to Aiko", "the CFO, Ahmed, said".
_AFTER = re.compile(r"(\b(?:with|to|from|cc|met|called|asked|told|per|and|CFO|CEO|VP|controller|champion)[,:]?\s+)([A-Z\u00c0-\u00de][\w'\-]+(?:[ -][A-Z\u00c0-\u00de][\w'\-]+)*)")
# Two or more capitalised words in a row, with accented letters: "José Núñez", "Kevin Smith", "Hugo van der Berg".
_W = r"[A-Z\u00c0-\u00de](?:[a-z\u00df-\u00ff]|'[A-Z])[\w'\-]*"
_PAIR = re.compile(rf"\b{_W}(?:\s+(?:van|von|de|der|den|da|di|del|le|la|bin|al)){{0,3}}\s+{_W}")
# Two or three capitalised words where the first is a known first name: "Marta Klein", "Jonas van Dijk".
_FIRSTS = "|".join(sorted(set(FIRST) | {"John", "Jane", "Mary", "James", "David", "Sarah", "Michael", "Laura", "Anna",
                                          "Peter", "Paul", "Maria", "Carlos", "Sofia", "Lucas", "Emma", "Olivia", "Noah"},
                          key=len, reverse=True))
_FULL = re.compile(rf"\b(?:{_FIRSTS})\s+(?:(?:van|von|de|da|di|del|le)\s+)?[a-zA-Z][a-zA-Z'\-]+\b", re.I)
_BEFORE_TAG = re.compile(r"\b([A-Z\u00c0-\u00de][\w'\-]+)\s+(?=\[)")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_PHONE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")


# Capitalised words that are not names: product, competitor, tool and calendar words a note may hold. Anything else
# capitalised in a name position is redacted; a false redaction costs a word, a missed one costs a person's privacy.
KEEP = {"I", "We", "The", "They", "He", "She", "It", "Next", "Said", "Sent", "Agreed", "Will", "Call", "Email", "Spoke",
        "Follow", "Follow-up", "Met", "Note", "See", "Lumen", "Ledger", "Lumen Ledger", "Meterly", "Billform", "Chargewell", "Ledgerline",
        "Quotient", "Quotient Billing", "Salesforce", "Snowflake", "NetSuite", "Stripe", "HubSpot", "BigQuery",
        "QuickBooks", "Zuora", "Chargebee", "Databricks", "SAP", "ERP", "CRM", "CFO", "CEO", "VP", "Q1", "Q2", "Q3", "Q4",
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December", "HIPAA", "SOC", "Excel", "Finance", "Legal",
        "Procurement", "Security", "Billing", "Revenue", "Operations", "Sales", "Marketing", "Engineering"}


def _keep(m: re.Match, whole: str | None = None) -> bool:
    words = (whole or m.group(0)).split()
    return all(w.strip(",.:'") in KEEP for w in words) or (whole or m.group(0)) in KEEP


def redact(text: str, contacts: list[tuple[str, str]]) -> str:
    """contacts: (full name, role label) from the CRM for this deal. Returns text with no person named."""
    out = _EMAIL.sub("[email]", text)
    out = _PROFILE.sub("[profile]", out)
    out = _PHONE.sub("[phone]", out)
    for full, role in sorted(contacts, key=lambda c: -len(c[0])):
        tag = f"[{role}]"
        parts = full.split()
        out = re.sub(re.escape(full), tag, out, flags=re.I)
        for part in (parts[-1], parts[0]) if len(parts) >= 2 else ():
            # A surname alone, or the first name alone, still names the person, in any case.
            out = re.sub(rf"(?<![\w\[])[\w'\-]*{re.escape(part)}[\w'\-]*(?![\w\]])", tag, out, flags=re.I)
        local = ".".join(p.lower() for p in parts)
        out = re.sub(rf"\b{re.escape(local)}\b", tag, out, flags=re.I)
    out = _TITLE.sub("[person]", out)
    out = _INITIALS.sub("[person]", out)
    out = _NON_LATIN.sub("[person]", out)
    out = _FULL.sub("[person]", out)
    out = _AFTER.sub(lambda m: m.group(0) if _keep(m, m.group(2)) else m.group(1) + "[person]", out)
    out = _PAIR.sub(lambda m: m.group(0) if _keep(m) else "[person]", out)
    # A capitalised word just before a redacted name is that person's other name: "Mark [controller]".
    out = _BEFORE_TAG.sub(lambda m: m.group(0) if m.group(1) in KEEP else "[person] ", out)
    return out
