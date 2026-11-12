"""The AI evals, replayed from their recordings (free, what CI does). A recording made with an older prompt is stale and
fails here, so a prompt change cannot ship without re-running the evals live. The floors in evals/thresholds.json
must hold on the replay."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from market import ai, llm

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"


def _cases(name):
    return [json.loads(x) for x in (EVALS / f"{name}.jsonl").read_text().splitlines() if x.strip()]


FIRST_PAYLOAD = {
    "classify": lambda c: ai.classify_payload(c["name"], c["description"]),
    "loss_code": lambda c: ai.loss_payload(c["text"], c["kind"]),
    "segment_story": lambda c: {"segment": c["segment"], "figures": c["figures"], "quotes": c["quotes"]},
    "proposal_text": lambda c: {"change": c["change"], "findings": c["findings"]},
}


@pytest.mark.parametrize("task", list(FIRST_PAYLOAD))
def test_every_case_has_a_current_recording(task):
    # The recordings are in the repo: a missing file is a failure, never a skip.
    assert (llm.RECORDINGS / f"{task}.jsonl").exists(), f"no recordings for {task}"
    recs = llm.recordings(task)
    current = llm.prompt_version(task)
    missing, stale = [], []
    for c in _cases(task):
        h = llm.input_hash(task, FIRST_PAYLOAD[task](c))
        if h not in recs:
            missing.append(c["id"])
        elif recs[h]["prompt_version"] != current:
            stale.append(c["id"])
    assert not stale, f"stale recordings (the prompt changed): {stale}"
    assert not missing, f"cases with no recording: {missing}"


def test_replay_meets_the_floors():
    out = subprocess.run([sys.executable, str(EVALS / "run.py")], capture_output=True, text=True, cwd=ROOT,
                         env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-2000:]
    results = json.loads((EVALS / "results-replay.json").read_text())
    failing = {k: v for k, v in results["floors"].items() if v.startswith("FAIL")}
    assert not failing, failing
    assert all((t or {}).get("not_run", 0) == 0 for t in results["tasks"].values()), "a case had no recording"
