# Pre-push hook (a proposal, not installed)

`make docs-check` fails when the README, `PROJECT-STATUS.md` or the decisions drift from the code. It needs no database and runs in well under a second, so it can run before every push. Nothing here is installed; copy it if you want it.

Save as `.git/hooks/pre-push` and make it executable (`chmod +x .git/hooks/pre-push`):

```sh
#!/bin/sh
# Refuse a push when the docs have drifted from the code.
make docs-check || { echo "pre-push: docs-check failed; fix the docs in the same commit as the change." >&2; exit 1; }
```

Skip it once with `git push --no-verify`. The same check also runs in the normal test suite (`tests/test_docs_check.py`), so CI catches a push that skipped the hook, except the Updated check, which needs full history.
