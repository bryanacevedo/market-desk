"""What this desk calls the other desks (the product rule of SESSIONS.md: standalone, and in harmony when integrated).
A desk's name appears on a screen only when INTEGRATED_WITH says that desk is connected (CRM=crmdesk also connects CRM Desk).
Alone, the same sentence says "your CRM", "your outreach tool" or "your events tool"."""
from __future__ import annotations

import re

from .config import CONFIG

REAL = {"crm_desk": "CRM Desk", "account_desk": "Account Desk", "events_desk": "Events Desk"}
PLAIN = {"crm_desk": "your CRM", "account_desk": "your outreach tool", "events_desk": "your events tool"}


def connected() -> set[str]:
    from . import crm
    if getattr(CONFIG, "public_demo", False):   # the sample shows the whole four-desk system by name, so a visitor can see what it is
        return set(REAL)
    return set(CONFIG.integrated_with) | ({"crm_desk"} if crm.enabled() else set())


def desk_names() -> dict[str, str]:
    on = connected()
    return {k: REAL[k] if k in on else PLAIN[k] for k in REAL}


def say(text: str | None, names: dict[str, str] | None = None) -> str | None:
    """The text with each desk's name replaced by the plain words when that desk is not connected."""
    if not text:
        return text
    names = names or desk_names()
    for key, real in REAL.items():
        if names[key] == real:
            continue
        plain = names[key]
        text = re.sub(rf"(^|[.!?] ){real}", lambda m, plain=plain: m.group(1) + plain[0].upper() + plain[1:], text)
        text = text.replace(real, plain)
    return text
