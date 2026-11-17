"""Docs gate: fails when the README, PROJECT-STATUS or the decisions drift from the code.

Run by `make docs-check` and by tests/test_docs_check.py, so the normal suite carries it. No database, no network,
well under a second. The logic is one function, `check(root)`, so a test can point it at a fixture in a temp dir.

Checks
  tests     the README carries no test count (no "186 tests", no tests badge): a number that nobody recomputes goes stale.
  migrations  any migration range written in the README, PROJECT-STATUS or docs equals the migrations folder, and the README writes one.
  env       every environment variable the code reads appears in the README or .env.example, or in docs/docs-check-allow.txt.
  decisions the highest decision number in docs/DECISIONS.md equals the count PROJECT-STATUS states ("1 to N").
  updated   PROJECT-STATUS 'Updated' is not more than 1 day older than the last commit touching code (skipped without git
            history, such as a shallow CI clone).
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

CODE_DIRS = ("src", "scripts", "evals", "migrations", "web/src", "tests")
ENV_DIRS = ("src", "scripts", "evals")
ENV_SUFFIXES = {".py", ".mjs", ".js"}
ENV_NAME = r"[A-Z][A-Z0-9_]*"
ENV_READS = [
    re.compile(r"(?:environ(?:\.get)?|getenv)\s*[\[(]\s*[\"'](" + ENV_NAME + r")[\"']"),
    re.compile(r"\b_flag\(\s*[\"'](" + ENV_NAME + r")[\"']"),
    re.compile(r"process\.env\.(" + ENV_NAME + r")"),
    re.compile(r"process\.env\[\s*[\"'](" + ENV_NAME + r")[\"']"),
]
LOOP = re.compile(r"for\s+\w+\s+in\s+\(([^)]*)\)")
QUOTED = re.compile(r"[\"'](" + ENV_NAME + r")[\"']")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def env_vars_read(root: Path) -> set[str]:
    found: set[str] = set()
    for d in ENV_DIRS:
        for f in sorted((root / d).rglob("*")) if (root / d).is_dir() else []:
            if f.suffix not in ENV_SUFFIXES or f.name == "docs_check.py" or "node_modules" in f.parts or ".venv" in f.parts:
                continue
            text = _read(f)
            for rx in ENV_READS:
                found.update(rx.findall(text))
            aliases = {a or n for n, a in re.findall(r"from\s+os\s+import\s+(environ|getenv)(?:\s+as\s+(\w+))?", text)}
            aliases |= {a + ".environ" for a in re.findall(r"import\s+os\s+as\s+(\w+)", text)}
            aliases |= {a + ".getenv" for a in re.findall(r"import\s+os\s+as\s+(\w+)", text)}
            for a in aliases - {"environ", "getenv"}:
                found.update(re.findall(re.escape(a) + r"(?:\.get)?\s*[\[(]\s*[\"'](" + ENV_NAME + r")[\"']", text))
            lines = text.splitlines()
            for i, line in enumerate(lines):  # a loop over a tuple of names that reads the environment
                m = LOOP.search(line)
                if m and "environ" in "\n".join(lines[i:i + 3]):
                    found.update(QUOTED.findall(m.group(1)))
    return found


def _allowed(root: Path) -> set[str]:
    names = set()
    for line in _read(root / "docs" / "docs-check-allow.txt").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.split()[0])
    return names


def _mentioned(root: Path) -> str:
    return _read(root / "README.md") + "\n" + _read(root / ".env.example")


def _check_tests(root: Path, problems: list[str]) -> None:
    readme = _read(root / "README.md")
    count = re.compile(r"badge/tests-|\d[\d,]*\*{0,2}\s+(?:passing\s+)?tests?\b(?:\s+cases?)?|\btests?:\s*\*{0,2}\d", re.I)
    for m in count.finditer(readme):
        problems.append(f"tests: README.md states a test count ({m.group(0).strip()!r}); drop it, it goes stale")


def _check_migrations(root: Path, problems: list[str]) -> None:
    files = sorted(p.name for p in (root / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")) if (root / "migrations").is_dir() else []
    if not files:
        return
    first, last = files[0][:4], files[-1][:4]
    rx = re.compile(r"migrations?[/`]*\s*\(?\s*(\d{4})\s*(?:to|-|through)\s*(\d{4})", re.I)
    seen = False
    docs = [root / "README.md", root / "PROJECT-STATUS.md", *sorted((root / "docs").glob("*.md"))]
    for f in docs:
        for a, b in rx.findall(_read(f)):
            seen = seen or f.name == "README.md"
            if (a, b) != (first, last):
                problems.append(f"migrations: {f.name} says {a} to {b}, the migrations folder runs {first} to {last}")
    if not seen:
        problems.append(f"migrations: README.md does not state the migration range ({first} to {last})")


def _check_env(root: Path, problems: list[str]) -> None:
    text, allowed = _mentioned(root), _allowed(root)
    for name in sorted(env_vars_read(root)):
        if name in allowed or re.search(r"(?<![A-Z0-9_])" + re.escape(name) + r"(?![A-Z0-9_])", text):
            continue
        problems.append(f"env: {name} is read by the code but is not in README.md or .env.example (or docs/docs-check-allow.txt)")


def _check_decisions(root: Path, problems: list[str]) -> None:
    decisions = _read(root / "docs" / "DECISIONS.md")
    numbers = [int(n) for n in re.findall(r"(?m)^(?:## )?(\d+)\. ", decisions)]
    if not numbers:
        problems.append("decisions: docs/DECISIONS.md has no numbered decisions")
        return
    dupes = sorted({n for n in numbers if numbers.count(n) > 1})
    missing = [n for n in range(1, max(numbers) + 1) if n not in numbers]
    if dupes:
        problems.append(f"decisions: DECISIONS.md numbers repeat: {dupes}")
    if missing:
        problems.append(f"decisions: DECISIONS.md skips numbers: {missing}")
    m = re.search(r"decisions\s+`?docs/DECISIONS\.md`?\s+1 to (\d+)", _read(root / "PROJECT-STATUS.md"))
    if not m:
        problems.append("decisions: PROJECT-STATUS.md does not state the count ('decisions `docs/DECISIONS.md` 1 to N')")
    elif int(m.group(1)) != max(numbers):
        problems.append(f"decisions: PROJECT-STATUS.md says 1 to {m.group(1)}, DECISIONS.md runs to {max(numbers)}")


def _git(root: Path, *args: str) -> str | None:
    try:
        run = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def _check_updated(root: Path, problems: list[str]) -> None:
    m = re.search(r"\*\*Updated:\*\*\s*(\d{4}-\d{2}-\d{2})", _read(root / "PROJECT-STATUS.md"))
    if not m:
        problems.append("updated: PROJECT-STATUS.md has no '**Updated:** YYYY-MM-DD'")
        return
    if _git(root, "rev-parse", "--is-shallow-repository") != "false":
        return  # no git, or a shallow clone: dates are not trustworthy
    paths = [d for d in CODE_DIRS if (root / d).exists()]
    last = _git(root, "log", "-1", "--format=%cs", "--", *paths)
    if not last:
        return
    gap = (dt.date.fromisoformat(last) - dt.date.fromisoformat(m.group(1))).days
    if gap > 1:
        problems.append(f"updated: PROJECT-STATUS.md says {m.group(1)}, the last commit touching code is {last}")


def check(root: Path | str) -> list[str]:
    """Every way the docs under `root` disagree with it; an empty list means they agree."""
    root = Path(root)
    problems: list[str] = []
    for step in (_check_tests, _check_migrations, _check_env, _check_decisions, _check_updated):
        step(root, problems)
    return problems


if __name__ == "__main__":
    found = check(Path(__file__).resolve().parents[1])
    for line in found:
        print(f"docs-check: {line}")
    print("docs-check: ok" if not found else f"docs-check: {len(found)} problem(s)")
    sys.exit(1 if found else 0)
