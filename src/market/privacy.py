"""Call-note redaction at import. A prospect's name never reaches the database: names from the CRM contact list
become the person's role in brackets, then a name-pattern pass catches titles and capitalised first-and-last-name
pairs that the contact list missed. The original text is never stored."""
from __future__ import annotations

import re

from .sim.names import FIRST

_TITLE = re.compile(r"\b(?:Mr|Ms|Mrs|Dr|Prof)\.?\s+[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?")
# Two or three capitalised words where the first is a known first name: "Marta Klein", "Jonas van Dijk".
_FIRSTS = "|".join(sorted(set(FIRST) | {"John", "Jane", "Mary", "James", "David", "Sarah", "Michael", "Laura", "Anna",
                                          "Peter", "Paul", "Maria", "Carlos", "Sofia", "Lucas", "Emma", "Olivia", "Noah"},
                          key=len, reverse=True))
_FULL = re.compile(rf"\b(?:{_FIRSTS})\s+(?:(?:van|von|de|da|di|del|le)\s+)?[A-Z][a-zA-Z'\-]+\b")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_PHONE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")


def redact(text: str, contacts: list[tuple[str, str]]) -> str:
    """contacts: (full name, role label) from the CRM for this deal. Returns text with no person named."""
    out = text
    for full, role in sorted(contacts, key=lambda c: -len(c[0])):
        tag = f"[{role}]"
        parts = full.split()
        out = re.sub(re.escape(full), tag, out)
        if len(parts) >= 2:
            # A surname alone, or the first name alone, still names the person.
            out = re.sub(rf"\b{re.escape(parts[-1])}\b", tag, out)
            out = re.sub(rf"\b{re.escape(parts[0])}\b", tag, out)
    out = _TITLE.sub("[person]", out)
    out = _FULL.sub("[person]", out)
    out = _EMAIL.sub("[email]", out)
    out = _PHONE.sub("[phone]", out)
    return out
