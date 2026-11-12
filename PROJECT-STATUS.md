# Market Desk: project status

**Updated:** 2026-11-11, 21:50. **Name:** Market Desk (Bryan, kickoff). **Plan:** `~/Developer/upstream-desk-plan/PLAN.md`.

## Where it stands

Stopped early: the session's usage limit was reached about 15 minutes into the overnight build. Nothing is built, committed, pushed or deployed.

Done:
- Read PLAN, RESEARCH and Account Desk's infrastructure (db, config, jobs, stats, scoring, llm, API auth, web shell, styles, sheets, Dockerfile, render.yaml, scripts, CI).
- Repo folder created with `git init` (no commits): LICENSE, .gitignore, .python-version copied from Account Desk.
- `docs/SPEC.md` written from the plan (section 15, gate 0 corrections, still empty).
- `docs/DECISIONS.md` 1 to 10.
- `docs/SCENARIOS.md` (P1 to P8 plus S1 to S13).

Started and stopped before finishing (results lost, rerun both):
- Gate 0 spec goldfish (fresh Opus reviewer).
- Eval-case writer (fresh Sonnet agent, blind to `src/`). Check `evals/` for partial files before rerunning; delete any partial `*.jsonl`.

Spec choices that differ from the plan (also to log in DECISIONS once confirmed by gate 0):
- P5 is shown through a `country` trait: Brazil has 9 opportunities, all at marketplaces.
- Sizing rows exist per segment and per region group, so DACH can be shown on Market.
- `drop_rule` also fires on `explained_by_size`, not only `not_clear`.
- Expected value = shrunk segment win rate x segment median ACV x score / 100.

## Checked locally

GitHub CLI logged in as bryanacevedo (needs to run outside the sandbox). Postgres 18.6, Node 26, uv present. Docker is not installed, so the image can only be built on Render.

## Gates 0 to 10

| Gate | Result |
|---|---|
| 0 Spec goldfish | Started, stopped by the usage limit. Not run. |
| 1 to 10 | Not run. |

## Next

Resume at PLAN section 12, row "22:00 to 22:45": rerun gate 0 and the eval writer, apply gate 0 fixes to SPEC, then scaffold from Account Desk.
