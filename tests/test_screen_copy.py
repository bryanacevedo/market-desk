"""The screen-copy gate (Events Desk lesson L-089): every sentence a screen can show is listed in docs/SCREEN-COPY.txt.
A new sentence fails this test until it is added there, where the diff shows it word for word."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_no_unlisted_sentence_on_any_screen():
    out = subprocess.run(["node", str(ROOT / "scripts" / "screen-copy.mjs")], capture_output=True, text=True, check=True).stdout
    found = {line.split("\t", 1)[1] for line in out.splitlines() if "\t" in line}
    listed = set((ROOT / "docs" / "SCREEN-COPY.txt").read_text().splitlines())
    new = sorted(found - listed)
    assert not new, f"new sentences on screens, review them and add to docs/SCREEN-COPY.txt: {new}"


def test_no_dashes_anywhere():
    """No em or en dashes in any file in the repo (Bryan's rule)."""
    bad = []
    for p in ROOT.rglob("*"):
        if any(x in p.parts for x in (".git", "node_modules", ".venv", "dist", ".data", "recordings")) or not p.is_file():
            continue
        if p.suffix not in {".py", ".ts", ".tsx", ".md", ".sql", ".css", ".json", ".jsonl", ".txt", ".yml", ".yaml", ".sh", ".mjs", ".html", ""}:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "" + chr(0x2014) + "" in text or "" + chr(0x2013) + "" in text:
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad
