# Decisions

Numbered. Each says what was decided, why, and what it costs.

## 1. Companies and roles, never named prospects
**What:** the desk stores companies, deal roles as persona and seniority, and redacted call notes. No prospect's name, email or phone enters the database. **Why:** a market tool does not need people; keeping them out leaves GDPR Article 14 notices and CCPA requests with the desks that contact people. **Cost:** buying-committee maps are by role, not by name, and a note's speaker is a role.

## 2. Account Desk's fit formula, ported from its code, not its spec text
**What:** fit is Account Desk's `scoring.fit` (lifecycle X, excludes, known-weight share, MIN_KNOWN 0.6, penalties, the profile's own tiers), plus an `eq` operator. Account Desk's SPEC sections 6 and 22.7 say tiers at A 70 and B 50 and show no penalties key; its `catalog.py` and `scoring.py` use penalties and tiers 85 and 65. The code is what runs, so the code was ported. **Why:** a company Market Desk calls A must be A in Account Desk. **Cost:** the port is a copy; if Account Desk's formula changes, the equivalence test (in `tests/test_handoff.py`) holds Market Desk's copy of that formula, not Account Desk's live code.

## 3. Ranges, not points
**What:** every sizing figure and every rate is shown as a range; no single TAM number exists on any screen. **Why:** a TAM point estimate claims a precision the inputs do not have. **Cost:** figures take more room and need a tap to see their parts.

## 4. The size check
**What:** every clear finding is checked within size bands with a Mantel-Haenszel odds ratio; if its 95% interval includes 1, the verdict is Explained by size. **Why:** size drives most B2B win rates, so a trait that only travels with size would otherwise become a rule. **Cost:** a real effect that is also concentrated in one size band can be called Explained by size; the finding still shows its crude figures.

## 5. Two people to publish a profile or activate a plan
**What:** the database refuses a profile published by its author and a plan activated by its author. **Why:** the profile decides every account's tier and owner; one person should not change it alone (Account Desk does the same for play launches). **Cost:** a desk with one RevOps person and no manager cannot publish; the plan's single-person exception was not built.

## 6. Win rates shrunk toward the overall rate for sizing
**What:** sizing and expected value use (wins + 20 x overall) / (opps + 20). The constant is a setting. **Why:** a segment with 9 deals and 5 wins would otherwise carry a 56% win rate into SOM. **Cost:** a small segment that really is better looks closer to average until it has deals.

## 7. Capacity in hours per account per month
**What:** A 1.0, B 0.4, C 0.1, X 0 hours a month per account (decision 17); 100 selling hours a month per person; ramp linear over 3 months (Bridge Group 2025 average). These are our assumptions, labelled as such on the Capacity tab and in Settings. **Why:** L-016: size by throughput times window times seats. **Cost:** the hours per tier are invented; a real team sets them.

## 8. Statistics copied from Account Desk, then extended
**What:** `stats.py` copies Account Desk's `wilson`, `newcombe`, `n_per_arm` and `fisher_greater` (intervals default to 90%), then adds a two-sided Fisher exact test, Holm, Mantel-Haenszel and a median interval. Every evidence call passes `conf=0.95` explicitly; segment tests use 90%, as Account Desk's play tests do. **Why:** one method across the desks; evidence about the profile is held to a stricter level than a test of a play. **Cost:** two levels in one product, stated in README.

## 9. RevOps role key is `revops`, not `gtm`
**What:** Account Desk calls Sam's role `gtm`; here it is `revops`. **Why:** this desk's owner is revenue operations. **Cost:** an install shared across desks maps the role.

## 10. Events Desk tier mapping
**What:** A is tier 1, B is tier 2, C and X are tier 3, written into the Events Desk document and checked by a test. **Why:** Events Desk tiers in prose by rules, not by weighted scores. **Cost:** a company near a boundary may read differently in Events Desk's own parser, which is untested on this file.

## 11. The world is exported for the other desks, with people only in the export
**What:** a stable export of companies, invented people and tiers, keyed by ids derived from domains, is the shared world's source for Account Desk and Events Desk later. People are generated from the seed at export time and never enter Market Desk's database. **Why:** Bryan asked for one universe across the desks (2026-11-11), and decision 1 keeps named people out of this desk. **Cost:** the people file is not a table anyone can query here; changing the generator changes the people, so the format carries a version.

## 12. Not judged is its own state
**What:** a company with under 60% of the profile's weight known shows as Not judged, not as C. Account Desk's code returns C with score 0 for the same company. **Why:** L-033: a gap is a third state; counting it as C hides how much of a segment is unknown, which sizing needs. **Cost:** the two desks show the same company differently; the handoff sends only A and B, so no exported tier differs.

## 13. Sizing ranges are scenario bounds
**What:** TAM, SAM and SOM low and high multiply the low ends and the high ends of their parts (ACV quartiles, Wilson bounds on the shrunk win rate, the account-to-opportunity rate). **Why:** the parts are not independent estimates, and a combined interval would need a model of how they move together that the data cannot support. **Cost:** the ranges are wide and are not confidence intervals; README says so.

## 14. SOM counts opportunities, not accounts
**What:** SOM multiplies worked accounts by the share that became opportunities before applying win rate. **Why:** gate 0 found the plan's formula treated every worked account as an opportunity, inflating SOM five to ten times. **Cost:** SOM depends on desk results; a desk with none uses the overall rate.

## 15. Explained by size needs the effect to shrink
**What:** a clear finding becomes Explained by size only when the size-adjusted interval includes 1 and the adjusted effect is at most half the crude one. **Why:** an interval that includes 1 can also mean too little data within bands; that is not confounding. **Cost:** a weak confounder that shrinks by less than half stays clear.

## 16. Only values with 30 opportunities are tested
**What:** the Holm family counts trait values with at least 30 opportunities; HQ city is tested for its 12 largest cities. **Why:** values that can never be clear only cost power; filtering by count does not look at outcomes. **Cost:** a value under 30 opportunities is never a rule, however lopsided.

## 17. Hours per account cut to a quarter of the plan's defaults
**What:** A 1.0, B 0.4, C 0.1 hours a month per worked account, and an account is worked for one quarter (four turns a year), instead of the plan's A 4.0, B 1.5, C 0.25 held all year. **Why:** at the plan's figures four SDRs hold 25 A accounts each, which contradicts the plan's own demo (about 1,100 accounts in Account Desk's last two books) and made the hiring gap read as hundreds of people and SOM as about $100,000 a year. Account Desk does the research and the drafting, so an SDR's hours per account are closer to an hour a month. Plan section 13 Q10 already marks these as invented assumptions for RevOps to edit. **Cost:** still invented; a real team measures its own hours per account.
