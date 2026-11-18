"""A job queue in Postgres. Claimed with FOR UPDATE SKIP LOCKED, so any number of workers can drain it safely.

A handler gets (cur, payload) and runs inside the job's own transaction: its writes and the job's 'done'
commit together, or roll back together and the job is retried with backoff.
"""
from __future__ import annotations

import logging
import os
import socket
import time
import traceback
from datetime import timedelta
from typing import Any, Callable

from . import db, telemetry
from .db import J

log = logging.getLogger("market.jobs")
Handler = Callable[[Any, dict], None]
HANDLERS: dict[str, Handler] = {}
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def handler(kind: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return wrap


def enqueue(cur, kind: str, payload: dict | None = None, *, delay: timedelta | None = None,
            run_at=None, dedupe_key: str | None = None, max_attempts: int = 5, keep_trace: bool = True) -> int | None:
    """Queue a job. With a dedupe_key, a second enqueue while the first is queued or running is a no-op.

    The job keeps the W3C traceparent of the span that queued it (NULL with tracing off), so its run joins that trace.
    A dedupe no-op inserts nothing, so the first job keeps its own value. `keep_trace=False` stores none."""
    row = db.one(cur, """
        insert into jobs (kind, payload, run_at, dedupe_key, max_attempts, trace_parent)
        values (%s, %s, coalesce(%s, app_now() + coalesce(%s, interval '0')), %s, %s, %s)
        on conflict (dedupe_key) where dedupe_key is not null and status in ('queued', 'running') do nothing
        returning id""", kind, J(payload or {}), run_at, delay, dedupe_key, max_attempts,
                telemetry.current_traceparent() if keep_trace else None)
    return row["id"] if row else None


def requeue(cur, kind: str, delay: timedelta) -> int | None:
    """A recurring job's handler queues its next run, deduped under the kind's own key. The handler runs while its row
    is still 'running', and the dedupe key covers 'running' rows, so a plain enqueue would be a silent no-op and the
    schedule would end after one run. The running row gives up the key first; this is inside the job's transaction,
    so a failed run rolls it back and the retry keeps the key.
    The next run starts its own trace: a schedule is not caused by the run before it."""
    db.run(cur, "update jobs set dedupe_key = null where dedupe_key = %s and status = 'running'", kind)
    return enqueue(cur, kind, {}, delay=delay, dedupe_key=kind, keep_trace=False)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


def run_ready(limit: int = 200) -> int:
    """Run jobs whose time has come, one transaction each. Returns how many ran."""
    ran = 0
    while ran < limit:
        with db.pool().connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    job = db.one(cur, """
                        select * from jobs where status = 'queued' and run_at <= app_now()
                        order by run_at, id limit 1 for update skip locked""")
                    if job is None:
                        return ran
                    db.run(cur, "update jobs set status = 'running', locked_at = now(), locked_by = %s, "
                                "attempts = attempts + 1 where id = %s", WORKER_ID, job["id"])
            fn = HANDLERS.get(job["kind"])
            error = None
            try:
                if fn is None:
                    raise RuntimeError(f"no handler for job kind {job['kind']}")
                with conn.transaction():
                    with conn.cursor() as cur:
                        with telemetry.job_span(job["kind"], job.get("trace_parent")):
                            fn(cur, job["payload"])
                        db.run(cur, "update jobs set status = 'done', finished_at = app_now() where id = %s", job["id"])
            except Exception as exc:  # the job's own writes rolled back; record the failure
                error = f"{type(exc).__name__}: {exc}"
                log.warning("job %s %s failed: %s", job["id"], job["kind"], error)
                log.debug(traceback.format_exc())
            if error is not None:
                with conn.transaction():
                    with conn.cursor() as cur:
                        attempts = job["attempts"] + 1
                        if attempts >= job["max_attempts"]:
                            db.run(cur, "update jobs set status = 'dead', last_error = %s, finished_at = app_now() "
                                        "where id = %s", error[:2000], job["id"])
                            from . import alerts
                            alerts.raise_alert(cur, kind="job_dead", severity="warn",
                                               title=f"A {job['kind']} job stopped after {attempts} tries",
                                               body=error[:500], object_kind="job", object_id=str(job["id"]),
                                               dedup_key=f"job_dead:{job['id']}")
                        else:
                            db.run(cur, "update jobs set status = 'queued', last_error = %s, "
                                        "run_at = app_now() + %s where id = %s", error[:2000], _backoff(attempts), job["id"])
        ran += 1
    return ran


def reap(cur, stale_minutes: int = 10) -> int:
    """Jobs a dead worker left in 'running' go back in line (or die after their last try). Uses the real clock:
    a lock is held in real time even when the demo's clock is simulated."""
    n = db.run(cur, """update jobs set status = case when attempts >= max_attempts then 'dead' else 'queued' end,
                       last_error = coalesce(last_error, '') || ' [reclaimed after the worker stopped]',
                       locked_by = null, run_at = app_now()
                       where status = 'running' and locked_at < now() - (%s || ' minutes')::interval""", stale_minutes)
    return n


def run_forever(poll_seconds: float = 2.0) -> None:  # pragma: no cover - the live worker loop
    while True:
        try:
            if run_ready() == 0:
                time.sleep(poll_seconds)
        except Exception:
            log.exception("worker loop error")
            time.sleep(poll_seconds)
