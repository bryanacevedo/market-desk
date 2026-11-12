# Market Desk: project status

**Updated:** 2026-11-12. **Spec:** `docs/SPEC.md` (section 15 holds the gate 0 corrections and wins where they differ); decisions `docs/DECISIONS.md` 1 to 30.

## Where it stands

Built end to end on a simulated world, overnight 2026-11-11 to 12. Public at https://github.com/bryanacevedo/market-desk; live at https://market-desk-3kou.onrender.com (first deploy healthy, pages not yet walked live).

Redesigned 2026-11-12 with its own spirit (`docs/DESIGN-CHECKLIST.md`, Spirit; decision 30).

Checked by running, on the demo database built from seed 7:
- 18,005 companies; 1,661 new-business and 166 expansion deals over 36 months; 286 customers, 35 of them churned; 2,248 call notes on 900 deals; 1,163 deals in the 24-month evidence window, 79 trait values tested; 53 tests passing; 45 rules-against-data checks passing.
- Every planted relationship P1 to P8 found by the desk's own rules (`docs/SCENARIO-COVERAGE.md`).
- The demo builds in about 35 seconds locally, in date order from November 2023 to 11 November 2026.

## Review gates

Every gate was run by a fresh agent that had not seen the build (never a fork), with a written brief.

| Gate | Date | Result |
|---|---|---|
| 0 Spec goldfish | 2026-11-11 | 1 blocker (SOM multiplied accounts by a per-opportunity win rate), 9 majors, 7 nits. All fixed in `docs/SPEC.md` 15 and decisions 12 to 16. Its cohort-split warning was confirmed by the build (decision 26). |
| 1 Docs against code | 2026-11-12 | 0 blockers, 10 majors, about 20 nits. Fixed: expansion tied to an "expand" decision; per-segment account-to-opportunity rate; overall signer for region rows; "A over capacity" on Accounts; erasure built; results import and webhook carry held-back rows and a test id; only a manager publishes; README placeholders; rescoring on publish is synchronous; a segment rule's evidence; balance flag counts hours; every owner move audited; doc corrections in SPEC 14a and decisions 4, 7, 20, 27. |
| 2 Rules against data | 2026-11-12 | Script: 45 checks in the suite, all passing. Its first run found 2 breaks (fixed: decision 25, capacity refresh). The fresh reviewer then found 12 more: results with deals the CRM never had, plans that knew a test's split before it started, a held-back company in a book made while its test ran, a profile citing evidence from after it was published, expansions after churn, notes written before their author joined, records stamped after today, an owner with no capacity row, segment capacity not adding up, and two checks that tested nothing. Fixed by building the demo in date order (`src/market/sim/story.py`) and adding a check for each. |
| 3 Scenario coverage | 2026-11-12 | `tests/test_scenarios.py`: 22 scenarios, all present (`docs/SCENARIO-COVERAGE.md`). It first found no Not judged company (fixed by planting vendor gaps). |
| 4 Design with copy | 2026-11-12 | 3 blockers (Evidence's date window read "10 Nov to 11 Nov"; a test's meeting rate worded as wins; Changes figures disagreeing with Evidence while the reviewer's database was being rebuilt), about 30 majors, many nits. Fixed: the window as a figure; the test wording; plain setting names; one title per sheet; no explainer lines on Territories, Capacity, Profile or Settings; one row per person for what changes; expected value and territory mean as two columns; story sentences then the buyers' words labelled once; phone rows as label and value; dates no longer shifted by time zone; Proposal sheet can make a draft; the layout check's false positive. Not fixed: ranges in small type beside rates are kept (PLAN 6 asks for them); no People section on the Company sheet, since this desk stores no people (decision 1). |
| 4b Three-desk design review | 2026-11-12 | After the redesign (ochre, Archivo, ranges as intervals, the market field; decision 30). Verdict: related and distinct on Market, thinner below it. 2 blockers (the field not drawn to scale; nested ranges gone on phones), 13 majors. Fixed: tiles exactly to scale with small segments gathered and labelled, tier A share written on each tile, ink text on tiles, log scale stated, one win-rate scale, ranges on Changes, Tests and the sheets, over capacity in ink past a 100% tick, Activate inside the halo, phone rows, earthy company marks. Not changed: the segment story and proposal wording on the demo come from stand-ins (decision 23). |
| 5 Compliance (Risk: legal, medium. Counsel to confirm.) | 2026-11-12 | 1 blocker (no erasure path), 7 majors. Fixed: erasure of a team member and of a company's notes, with tests; redaction now catches case, initials, accents, non-Latin script, particles, hyphenated names, profile links and names after "with", "to", "CFO"; the 50-name test uses names from outside the generator's lists; the Events Desk document and the world export leave out sole traders and restricted or model-read values; the export refuses outside the demo (decisions 27, 28). Known limit in README. |
| 6 Security | 2026-11-12 | 1 blocker (an SDR could read deal sizes through a profile version), 8 majors. Fixed: role checks on versions and findings; `MODE=live` needs header auth; JSON-only writes (CSRF); webhook body cap, replay refusal, row validation and rate limit; recordings written only by the eval runner; per-visitor rate limit behind Render's proxy and a 1 MB body cap; link gate and case-free name gate on the model's prose; CSV formula guard; generic errors; HSTS; API docs off on the demo; MCP strips money itself. |
| 7 Eval floors | 2026-11-12 | Passed on the live run and on replay (`tests/test_evals.py`). Safety floors 100%; judge-faithful 85% (stories) and 90% (proposals) after prompt fixes forced by the first run (35% and 55%). Three live runs, $1.92 in all. |
| 8 Final whole-system goldfish | 2026-11-12 | Two reviewers. Code and demo: 1 blocker (Expand accepted a test that did worse), 11 majors; fixed in the engine (expand needs a lift, drops only weak rules, SOM adds up, capacity only to worked segments, test hours, results by book date, the Events Desk document says only what evidence says). Docs: 7 majors, all fixed (private references removed, the floors disclosed, P4's base, test claims worded to what the tests check). |
| 9 Deep doc sweep | 2026-11-12 | Fresh reviewer re-read every number from the database, tests and eval results: 96 right, 7 wrong (deal count, open share, two DACH figures rounded differently from the screen, scenario count, build time, a stale note), all fixed; no dashes; every page, sheet, file, command and README link exists; 13 screen terms added to the glossary. |
| 10 Deploy and live check | 2026-11-12 | Live at https://market-desk-3kou.onrender.com, serving the redesigned build (Render auto-deploy did not fire on later pushes; deploys are started through Render's API). Checked as a visitor: every page's endpoint as RevOps, the manager and an SDR (all 200; the SDR is refused Market and profile versions and receives no money fields); the Segment, Finding, Company, Proposal and Book sheets' endpoints; the results webhook refuses uploads on the demo; API docs are off; Territories at 375 wide with no sideways scroll. |

## Proven and not proven

Proven by tests on real Postgres 18: statistics against published values; the size check; fit reproduces from stored inputs; two-person publish and activate; the held-back trigger; Account Desk equivalence on every exported company with its fields known; the Events Desk document's headings, numbers and tiers; 50 planted names never reach the database; the AI gates on failing fixtures; exporting the shared world twice from one database gives identical files; two builds of the world from its seed write identical rows (checked on a 1,500-company world without the story).

Not proven: anything against a real CRM, vendor or public count; Account Desk or Events Desk importing these files; header auth through Cloudflare Access.

## What was cut

Nothing from the plan's cut list so far. The MCP server is built (4 read-only tools).

## Next

- An Account Desk change: accept pricing model and segment, so usage pricing stops being a dropped rule.
- Have Account Desk and Events Desk load the shared world export.
- A walkthrough video.
- Publishing a profile version does not redraw the plan; RevOps drafts a new plan after it (worth automating as a draft).
