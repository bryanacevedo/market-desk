"""The docs gate (scripts/docs_check.py): passes on this repo, and each check fails on a broken fixture."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("docs_check", ROOT / "scripts" / "docs_check.py")
docs_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs_check)


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _fixture(root: Path) -> Path:
    _write(root, "README.md", "# Desk\nMigrations in `migrations/` (0001 to 0003).\nSet `FOO_KEY` and `BAR_FLAG`.\n")
    _write(root, "PROJECT-STATUS.md", "**Updated:** 2026-11-16. decisions `docs/DECISIONS.md` 1 to 2.\n")
    _write(root, "docs/DECISIONS.md", "# Decisions\n## 1. One\ntext\n## 2. Two\ntext\n")
    for n in ("0001_a", "0002_b", "0003_c"):
        _write(root, f"migrations/{n}.sql", "select 1;")
    _write(root, "src/app.py", "import os\nkey = os.environ.get('FOO_KEY')\nflag = _flag('BAR_FLAG')\n")
    return root


def test_the_real_repo_passes():
    assert docs_check.check(ROOT) == []


def test_the_fixture_passes(tmp_path):
    assert docs_check.check(_fixture(tmp_path)) == []


def test_a_test_count_in_the_readme_fails(tmp_path):
    root = _fixture(tmp_path)
    _write(root, "README.md", (root / "README.md").read_text() + "186 tests pass.\n![t](https://img.shields.io/badge/tests-53-green)\n")
    problems = docs_check.check(root)
    assert sum(p.startswith("tests:") for p in problems) == 2
    for text in ("201 test cases", "**53** tests", "tests: 53", "53 Tests"):
        _write(root, "README.md", "Migrations in `migrations/` (0001 to 0003). `FOO_KEY` `BAR_FLAG`\n" + text + "\n")
        assert any(p.startswith("tests:") for p in docs_check.check(root)), text


def test_a_wrong_or_missing_migration_range_fails(tmp_path):
    root = _fixture(tmp_path)
    _write(root, "README.md", (root / "README.md").read_text().replace("0001 to 0003", "0001 to 0002"))
    assert any(p.startswith("migrations:") and "0002" in p for p in docs_check.check(root))
    _write(root, "README.md", "Set `FOO_KEY` and `BAR_FLAG`.\n")
    assert any(p.startswith("migrations:") and "does not state" in p for p in docs_check.check(root))


def test_an_undocumented_env_variable_fails_until_allowed(tmp_path):
    root = _fixture(tmp_path)
    _write(root, "src/more.py", "import os\nx = os.environ['NEW_VAR']\nfor v in ('PGHOST', 'PGUSER'):\n    os.environ.get(v)\n")
    problems = [p for p in docs_check.check(root) if p.startswith("env:")]
    assert {p.split()[1] for p in problems} == {"NEW_VAR", "PGHOST", "PGUSER"}
    _write(root, "docs/docs-check-allow.txt", "# why\nNEW_VAR a system variable\nPGHOST x\nPGUSER y\n")
    assert [p for p in docs_check.check(root) if p.startswith("env:")] == []
    _write(root, ".env.example", "FOO_KEY=\n")  # a name in .env.example counts as documented
    _write(root, "README.md", (root / "README.md").read_text().replace("`FOO_KEY`", ""))
    assert [p for p in docs_check.check(root) if p.startswith("env:")] == []


def test_migration_range_match_is_case_insensitive(tmp_path):
    root = _fixture(tmp_path)
    _write(root, "PROJECT-STATUS.md", (root / "PROJECT-STATUS.md").read_text() + "Migrations 0001 to 0002 are applied.\n")
    assert any(p.startswith("migrations:") and "PROJECT-STATUS" in p for p in docs_check.check(root))


def test_aliased_environ_imports_are_caught(tmp_path):
    root = _fixture(tmp_path)
    _write(root, "src/a.py", "from os import environ\nx = environ['ALPHA_VAR']\n")
    _write(root, "src/b.py", "from os import environ as e\ny = e.get('BETA_VAR')\n")
    _write(root, "src/c.py", "import os as o\nz = o.getenv('GAMMA_VAR')\n")
    names = {p.split()[1] for p in docs_check.check(root) if p.startswith("env:")}
    assert names == {"ALPHA_VAR", "BETA_VAR", "GAMMA_VAR"}


def test_duplicate_or_missing_decision_numbers_fail(tmp_path):
    root = _fixture(tmp_path)
    _write(root, "docs/DECISIONS.md", "## 1. One\n## 2. Two\n## 2. Again\n")
    assert any("repeat" in p for p in docs_check.check(root))
    _write(root, "docs/DECISIONS.md", "## 1. One\n## 3. Three\n")
    assert any("skips" in p for p in docs_check.check(root))


def test_a_decision_count_mismatch_fails(tmp_path):
    root = _fixture(tmp_path)
    _write(root, "docs/DECISIONS.md", (root / "docs/DECISIONS.md").read_text() + "## 3. Three\ntext\n")
    assert any(p.startswith("decisions:") and "1 to 2" in p for p in docs_check.check(root))


@pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0, reason="needs git")
def test_a_stale_updated_date_fails(tmp_path):
    root = _fixture(tmp_path)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_COMMITTER_DATE": "2026-11-20T12:00:00", "GIT_AUTHOR_DATE": "2026-11-20T12:00:00", "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)
    assert any(p.startswith("updated:") for p in docs_check.check(root))  # 2026-11-16 against a 2026-11-20 code commit
    _write(root, "PROJECT-STATUS.md", (root / "PROJECT-STATUS.md").read_text().replace("2026-11-16", "2026-11-19"))
    assert [p for p in docs_check.check(root) if p.startswith("updated:")] == []


def test_updated_check_is_skipped_without_git(tmp_path):
    assert [p for p in docs_check.check(_fixture(tmp_path)) if p.startswith("updated:")] == []
