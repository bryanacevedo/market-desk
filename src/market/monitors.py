"""Checks that run on a schedule and raise alerts as rows."""
from __future__ import annotations

from . import alerts, db


def stale_sources(cur) -> list[str]:
    """A source that has not finished a run within its cadence raises an alert."""
    rows = db.all(cur, """
        select s.key, s.label, s.cadence_hours, max(r.finished_at) as last
        from sources s left join source_runs r on r.source = s.key and r.error is null
        group by s.key, s.label, s.cadence_hours
        having max(r.finished_at) is null or max(r.finished_at) < app_now() - make_interval(hours => s.cadence_hours)""")
    out = []
    for r in rows:
        alerts.raise_alert(cur, kind="source_stale", severity="warn", title=f"{r['label']} missed its run",
                           body=f"Last finished {r['last']:%d %b %H:%M}" if r["last"] else "Never ran",
                           object_kind="source", object_id=r["key"], dedup_key=f"source_stale:{r['key']}:{r['last']}")
        out.append(r["key"])
    return out


def run_all(cur) -> dict:
    return {"stale_sources": stale_sources(cur)}
