"""Alerts are rows first, so an alert survives a dead channel and the health check can see it."""
from __future__ import annotations

from . import db


def raise_alert(cur, *, kind: str, severity: str, title: str, body: str, object_kind: str | None = None,
                object_id: str | None = None, dedup_key: str | None = None) -> int | None:
    row = db.one(cur, """insert into alerts (kind, severity, title, body, object_kind, object_id, dedup_key, at)
                         values (%s, %s, %s, %s, %s, %s, %s, app_now()) on conflict (dedup_key) do nothing returning id""",
                 kind, severity, title, body, object_kind, object_id, dedup_key)
    return row["id"] if row else None
