# Market Desk: project status

**Updated:** 2026-11-12. **Name:** Market Desk (Bryan's kickoff). **Plan:** `~/Developer/upstream-desk-plan/PLAN.md`; spec `docs/SPEC.md` (section 15 holds the gate 0 corrections and wins where they differ); decisions `docs/DECISIONS.md` 1 to 26.

## Where it stands

Built end to end on a simulated world, overnight 2026-11-11 to 12, in one pass at the Account Desk bar. Not yet published or deployed (see the gate log).

Checked by running, on the demo database built from seed 7:
- 18,005 companies; 1,559 new-business and 197 expansion deals over 36 months; 304 customers, 41 of them churned; 2,205 call notes on 900 deals; 1,167 deals in the 24-month evidence window, 77 trait values tested.
- Every planted relationship P1 to P8 found by the desk's own rules (`docs/SCENARIO-COVERAGE.md`).
- The demo builds in about 30 seconds locally.

## Review gates

| Gate | Date | Result |
|---|---|---|
| 0 Spec goldfish | 2026-11-11 | Fresh Opus reviewer: 1 blocker (SOM multiplied accounts by a per-opportunity win rate), 9 majors, 7 nits. All fixed in `docs/SPEC.md` 15 and decisions 12 to 16; the cohort-split and recomputed-sample finding was confirmed later by the build (decision 26). |
| 1 Goldfish, docs against code | | Not run yet |
| 2 Rules against data | 2026-11-12 | `scripts/audit_rules.py`, 33 checks, in the suite. Its first run found 2 real breaks: 18 held-back test companies had been in an earlier Account Desk book (fixed: decision 25), and a manual move did not refresh capacity (fixed). Reviewer part not run yet. |
| 3 Scenario coverage | 2026-11-12 | `tests/test_scenarios.py`: 21 scenarios, all present. It first found no Not judged company (fixed by planting vendor gaps). |
| 4 Design review with copy | | Not run yet |
| 5 Compliance | | Not run yet |
| 6 Security | | Not run yet |
| 7 Eval floors | | Live run in progress |
| 8 Final whole-system goldfish | | Not run yet |
| 9 Deep doc sweep | | Not run yet |
| 10 Deploy and live check | | Not run yet |

## Proven and not proven

Proven by tests on real Postgres 18: statistics against published values; the size check; fit reproduces from stored inputs; two-person publish and activate; the held-back trigger; Account Desk equivalence on every exported company with its fields known; the Events Desk document's headings, numbers and tiers; 50 planted names never reach the database; the AI gates on failing fixtures; the shared world export is identical across two builds; two world builds write identical rows.

Not proven: anything against a real CRM, vendor or public count; Account Desk or Events Desk importing these files; header auth through Cloudflare Access.

## What was cut

Nothing from the plan's cut list so far. The MCP server is built (4 read-only tools).

## Next

- Account Desk change (plan Q6): accept pricing model and segment, so usage pricing stops being a dropped rule.
- Have Account Desk and Events Desk load the shared world export.
- A walkthrough video (plan Q9).
