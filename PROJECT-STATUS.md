# Market Desk: project status

**Updated:** 2026-11-12. **Name:** Market Desk (Bryan's kickoff). **Plan:** `~/Developer/upstream-desk-plan/PLAN.md`; spec `docs/SPEC.md` (section 15 holds the gate 0 corrections and wins where they differ); decisions `docs/DECISIONS.md` 1 to 26.

## Where it stands

Built end to end on a simulated world, overnight 2026-11-11 to 12, in one pass at the Account Desk bar. Not yet published or deployed (see the gate log).

Checked by running, on the demo database built from seed 7:
- 18,005 companies; 1,647 new-business and 166 expansion deals over 36 months; 286 customers, 35 of them churned; 2,248 call notes on 900 deals; 1,163 deals in the 24-month evidence window, 79 trait values tested; 53 tests passing; 45 rules-against-data checks passing.
- Every planted relationship P1 to P8 found by the desk's own rules (`docs/SCENARIO-COVERAGE.md`).
- The demo builds in about 35 seconds locally, in date order from 2024 to 11 November 2026.

## Review gates

Every gate was run by a fresh agent that had not seen the build (never a fork), with a written brief.

| Gate | Date | Result |
|---|---|---|
| 0 Spec goldfish | 2026-11-11 | 1 blocker (SOM multiplied accounts by a per-opportunity win rate), 9 majors, 7 nits. All fixed in `docs/SPEC.md` 15 and decisions 12 to 16. Its cohort-split warning was confirmed by the build (decision 26). |
| 1 Docs against code | 2026-11-12 | 0 blockers, 10 majors, about 20 nits. Fixed: expansion tied to an "expand" decision; per-segment account-to-opportunity rate; overall signer for region rows; "A over capacity" on Accounts; erasure built; results import and webhook carry held-back rows and a test id; only a manager publishes; README placeholders; rescoring on publish is synchronous; a segment rule's evidence; balance flag counts hours; every owner move audited; doc corrections in SPEC 14a and decisions 4, 7, 20, 27. |
| 2 Rules against data | 2026-11-12 | Script: 45 checks in the suite, all passing. Its first run found 2 breaks (fixed: decision 25, capacity refresh). The fresh reviewer then found 12 more: results with deals the CRM never had, plans that knew a test's split before it started, a held-back company in a book made while its test ran, a profile citing evidence from after it was published, expansions after churn, notes written before their author joined, records stamped after today, an owner with no capacity row, segment capacity not adding up, and two checks that tested nothing. Fixed by building the demo in date order (`src/market/sim/story.py`) and adding a check for each. |
| 3 Scenario coverage | 2026-11-12 | `tests/test_scenarios.py`: 21 scenarios, all present (`docs/SCENARIO-COVERAGE.md`). It first found no Not judged company (fixed by planting vendor gaps). |
| 4 Design with copy | 2026-11-12 | 3 blockers (Evidence's date window read "10 Nov to 11 Nov"; a test's meeting rate worded as wins; Changes figures disagreeing with Evidence while the reviewer's database was being rebuilt), about 30 majors, many nits. Fixed: the window as a figure; the test wording; plain setting names; one title per sheet; no explainer lines on Territories, Capacity, Profile or Settings; one row per person for what changes; expected value and territory mean as two columns; story sentences then the buyers' words labelled once; phone rows as label and value; dates no longer shifted by time zone; Proposal sheet can make a draft; the layout check's false positive. Not fixed: ranges in small type beside rates are kept (PLAN 6 asks for them); no People section on the Company sheet, since this desk stores no people (decision 1). |
| 5 Compliance (Risk: legal, medium. Counsel to confirm.) | 2026-11-12 | 1 blocker (no erasure path), 7 majors. Fixed: erasure of a team member and of a company's notes, with tests; redaction now catches case, initials, accents, non-Latin script, particles, hyphenated names, profile links and names after "with", "to", "CFO"; the 50-name test uses names from outside the generator's lists; the Events Desk document and the world export leave out sole traders and restricted or model-read values; the export refuses outside the demo (decisions 27, 28). Known limit in README. |
| 6 Security | 2026-11-12 | 1 blocker (an SDR could read deal sizes through a profile version), 8 majors. Fixed: role checks on versions and findings; `MODE=live` needs header auth; JSON-only writes (CSRF); webhook body cap, replay refusal, row validation and rate limit; recordings written only by the eval runner; per-visitor rate limit behind Render's proxy and a 1 MB body cap; link gate and case-free name gate on the model's prose; CSV formula guard; generic errors; HSTS; API docs off on the demo; MCP strips money itself. |
| 7 Eval floors | 2026-11-12 | Passed on the live run and on replay (`tests/test_evals.py`). Safety floors 100%; judge-faithful 85% (stories) and 90% (proposals) after prompt fixes forced by the first run (35% and 55%). Three live runs, $1.92 in all. |
| 8 Final whole-system goldfish | | Running |
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
