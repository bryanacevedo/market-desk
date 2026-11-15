"""The hourly jobs keep their schedule. A handler runs while its own row is 'running', and a dedupe key covers
'running' rows, so a handler that queues its next run with the key it was queued under queues nothing (the schedule
silently ends after one run). These tests put the row in the state the worker gives it and run the real handler."""
from __future__ import annotations

from datetime import timedelta

from market import crm, db, deals_in, jobs, mqa


def _running(cur, kind: str) -> None:
    """What the worker has done to the job before it calls the handler."""
    jobs.enqueue(cur, kind, {}, dedupe_key=kind)
    db.run(cur, "update jobs set status = 'running' where kind = %s and status = 'queued'", kind)


def _queued(cur, kind: str) -> int:
    return db.val(cur, "select count(*) from jobs where kind = %s and status = 'queued'", kind)


def test_the_crm_pull_job_queues_its_next_run_while_it_is_running(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setenv("CRM_PULL", "1")
    monkeypatch.setattr(crm.CrmDeskReader, "from_env", classmethod(lambda cls: object()))
    monkeypatch.setattr(deals_in, "pull", lambda *a, **k: None)
    _running(cur, "crm_pull")
    crm._pull(cur, {})
    assert _queued(cur, "crm_pull") == 1


def test_the_mqa_job_queues_its_next_run_while_it_is_running(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setenv("CRM_DESK_URL", "http://crm.invalid")
    monkeypatch.setenv("CRM_DESK_KEY", "k")
    monkeypatch.setattr(mqa, "sync", lambda *a, **k: None)
    _running(cur, "crm_mqa")
    mqa._run(cur, {})
    assert _queued(cur, "crm_mqa") == 1


def test_a_second_enqueue_from_outside_is_still_a_no_op_while_the_next_run_waits(cur):
    _running(cur, "crm_pull")
    jobs.requeue(cur, "crm_pull", timedelta(minutes=15))
    assert jobs.enqueue(cur, "crm_pull", {}, dedupe_key="crm_pull") is None   # one chain, never two
    assert _queued(cur, "crm_pull") == 1


def test_requeue_without_a_running_row_still_queues_one(cur):
    jobs.requeue(cur, "crm_pull", timedelta(minutes=15))
    jobs.requeue(cur, "crm_pull", timedelta(minutes=15))
    assert _queued(cur, "crm_pull") == 1
