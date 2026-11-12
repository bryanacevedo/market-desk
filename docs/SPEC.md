# Market Desk: specification

**Written:** 2026-11-11 from the build plan and its research (kept outside this repo). Corrected by the gate 0 review (section 15). Where this spec and the plan differ, this spec wins and the difference is in `docs/DECISIONS.md`.

Market Desk decides who a B2B team sells to. It learns the ideal customer profile from every deal won, lost and churned; sizes each segment the team can reach and work; tiers every company and assigns it to someone with room to work it; hands that book to Account Desk and Events Desk; and proposes profile changes when their results say the profile was wrong. It stores companies and roles, never named prospects.

## 1. Scope

In: evidence by trait; a versioned profile published by a second person; fit, tier and segment for every company; sizing as ranges (TAM, reachable SAM, capacity-bound SOM); capacity, territories and assignment with a draft plan activated by a manager; versioned target books for Account Desk (CSV and ICP JSON) and Events Desk (ICP markdown); results read back by account; segment tests with a held-back group; proposals decided by code and worded by a model.

Out: signals and plays (Account Desk), finding or contacting people (both other desks), quota and compensation, inbound routing, ad audiences, pricing, live vendor adapters (contracts only), login (an "acting as" menu in the demo; header auth through Cloudflare Access for a real install, unproven).

## 2. Stack

Python 3.13 with uv, FastAPI, psycopg 3, Postgres 18, plain SQL migrations applied at server start. Jobs in a Postgres table claimed with `FOR UPDATE SKIP LOCKED`. Package `market`, CLI `python -m market`. React, Vite and TypeScript under `web/`, served by the API, with Account Desk's Instrument identity copied (styles, shared parts, sheets, status icons). Model calls through one function with structured outputs, recordings and a deterministic stand-in. Model under test Claude Opus 5.5 (`claude-opus-5-5`), judge Claude Sonnet 5.5 (`claude-sonnet-5-5`). Tests with pytest on real Postgres. Demo on Render's free plan in Docker with Postgres inside and the demo database built into the image.

## 3. Roles

| Role key | Who in the demo | Can |
|---|---|---|
| `revops` | Sam Kowalski | Own the profile, sources, settings and plans; draft profile versions and plans; make a proposal a draft; dismiss proposals; start and decide segment tests; create target books. |
| `manager` | Elena Duarte | Publish a profile version she did not author (only a manager publishes); activate a plan she did not author; dismiss proposals; decide segment tests. |
| `sdr` | Maya Okafor, Daniel Reyes, Priya Natarajan, Tom Whitaker, Nadia Haddad (starts 2026-12-01) | See My book and Accounts filtered to their own. |
| `ae` | Grace Lindqvist, Omar Bello, Hannah Mercer | Same as SDR. |

Company money (deal sizes, TAM, SAM, SOM in dollars, expected value, costs) is returned by the API only to `revops` and `manager`. For other roles the API leaves those keys out; hiding in the browser is not the control.

## 4. Data model

One migration `0001_core.sql`; later fixes are new numbered files. Money is integer cents. Tables people change carry `created_at` and `created_by`. `app_now()` reads the desk clock (`sim_clock`), which the demo sets to 2026-11-11 12:00 UTC.

Tables (see `migrations/0001_core.sql`), with these columns settled:

- `companies` adds `hq_city text`, `founded_year int`, `country text` (ISO 2), `region_group text` (`North America` (US, CA, MX, as Account Desk's `region_of`), `UK and Ireland`, `DACH`, `France and Benelux`, `Nordics`, `Southern Europe`, `Latin America` (BR, AR), `Asia Pacific`), `sole_trader bool`. `region` is Account Desk's `setup_desk.region_of(country)` copied exactly.
- `sources` adds `cadence_hours int` and `no_redistribution bool`.
- `deals.snapshot` holds `industry, employees, region, region_group, country, revenue_band, pricing_model, tech, hq_city, founded_year` as they were on `created_at`.
- `account_fit` primary key (company, icp_version); `inputs` holds the exact company fields used; `score` null when not judged.
- `segment_sizing` adds `dimension` (`segment` or `region_group`) and `key`; a row exists per segment and per region group.
- `findings` adds `trait` (the field) and `mh_or`, `mh_low`, `mh_high` (stored, never shown).
- `target_book_rows` (book, company, tier, owner, segment, test_member bool) so the held-back trigger can see rows.
- `erasures` (kind, subject, at, by) records each erasure without the erased data.

CHECKs the schema holds: `deals.closed_at >= created_at`; `outcome = 'open'` iff `closed_at is null`; `assignments.reason_code = 'manual'` requires a note; one `published` profile (partial unique index); one `active` plan (partial unique index); `customers.churned_on >= started_on`; tier in A, B, C, X; amounts not negative. Triggers: a profile version cannot be published by its author; a plan cannot be activated by its author; a held-back member of a running test cannot be written to `target_book_rows` of an `account_desk` book; a source with `no_redistribution` cannot feed a book (checked in code, section 9.4).

## 5. The simulated world

Seller Lumen Ledger (usage-based billing and revenue recognition for B2B software), same as Account Desk. Fixed seed; two builds write identical rows (test compares a hash of every table's content).

Counts: 18,000 companies; about 1,200 public count cells (country by industry by size band) totalling about 23% above the universe, DACH and France under-covered; about 1,500 new-business deals at about 1,200 companies over 36 months plus about 220 expansion deals; about 300 customers, about 12% churned a year; about 2,400 call notes on about 900 deals; 2 to 7 deal roles per deal; desk results for the accounts in the last two target books and about 180 accounts met at 4 events.

Planted relationships, in `PLANTED` in `src/market/sim/world.py` and in README:

| Key | What is planted | What the code must say |
|---|---|---|
| P1 | Usage pricing wins new business at about 38%, others about 16%, independent of size and region. About 15% of companies have pricing unknown. | Clearly higher; proposes `add_rule`; the Account Desk handoff lists it as dropped. |
| P2 | 2,000 to 4,999 employees win about 8% with cycles about twice as long. | Clearly lower; proposes a penalty. |
| P3 | Healthcare software loses, about 60% of losses coded `compliance`. | Clearly lower with the loss mix; proposes an exclude with the reason. |
| P4 | Salesforce users win more in the crude cut only because they cluster in the 120 to 1,999 sweet spot. | Explained by size. |
| P5 | Brazil: 9 opportunities, all at marketplaces, 5 won. | Too few to tell; never a rule. |
| P6 | DACH: the signer role findable for about 40% of companies against about 85% elsewhere. | DACH SAM far below its TAM on Market. |
| P7 | Two finished segment tests of 520 accounts: fintech 120 to 499 (meetings 22% worked against 10% held back) and developer tools (11% against 10%). | One `segment_expand` proposal; developer tools read as no clear difference. |
| P8 | HQ city and founding year carry no effect. | No finding on either is clear. |

The demo opens on 2026-11-11 with profile v3 published (Account Desk's ICP with evidence attached), draft v4 holding the P1 and P2 changes, an active plan, a draft plan for Q1 2027, at least one open proposal, one running test and one read test.

### 5.1 The shared world export

The simulated world is meant to become the shared universe for all three desks later (the owner's direction, 2026-11-11). `python -m market world-export DIR` writes, from the demo database and the fixed seed:

- `companies.csv`: `world_id,name,domain,parent_domain,industry,employees,country,region,region_group,revenue_band,pricing_model,tech,lifecycle,hq_city,founded_year`. `world_id` is `co_` plus the first 12 hex characters of sha256 of the domain, so it is stable across builds and does not depend on database ids.
- `people.csv`: `world_id,company_world_id,first_name,last_name,title,persona,seniority,email`. Invented people, generated from the seed and the company's `world_id` only (never from the database), 2 to 6 per company for tier A and B companies of the published profile. They are written to the export file only; Market Desk never stores them in its database (decision 1). `world_id` is `pe_` plus 12 hex characters of sha256 of company world id and the person's index.
- `tiers.csv`: `company_world_id,icp_version,score,tier,segment,owner_email`.
- `manifest.json`: seed, build date, row counts, sha256 of each file, the seller (Lumen Ledger) and a format version.

A test builds the export twice from the same seed and requires identical files. README documents the format as the shared world's source. Account Desk and Events Desk are not changed tonight.

## 6. Evidence (`evidence.py`)

Window: new-business deals closed in the last 24 months (setting `evidence_window_months`). Traits read from the deal snapshot: industry, size band (20 to 119, 120 to 499, 500 to 1,999, 2,000 to 4,999, 5,000+), region, country, revenue band, pricing model, each technology, deal source, HQ city, founding period (before 2000, 2000 to 2009, 2010 to 2014, 2015 to 2019, 2020 on), and segment. Unknown values are not a trait value.

Per trait value with at least one opportunity: opportunities, wins, win rate with a Wilson 95% interval; the rest's opportunities and wins; difference with a Newcombe 95% interval; Fisher exact two-sided p; won-deal cycle median with a distribution-free 95% interval from binomial order statistics; ACV median and quartiles on won deals; 12-month churn of customers it produced, with n; the top three loss codes with shares.

Verdicts: `too_few` below 30 opportunities or 5 wins (settings `min_opps`, `min_wins`); else `clear_higher` or `clear_lower` when p is below its Holm step-down threshold at family alpha 0.05 across every trait value tested in the run (every value with at least one opportunity, including those later called too few); else `not_clear`. Size check on every clear finding not on the size trait: Mantel-Haenszel odds ratio across the five size bands with a 95% interval (Robins, Breslow and Greenland variance); if the interval includes 1, the verdict becomes `explained_by_size`. A run is kept with its settings; the Evidence page shows changes since the previous run.

## 7. Fit, tiers and segments (`fit.py`)

Rules shape: `factors` (key, field, op, value, weight, evidence, why), `penalties` (same), `excludes` (key, field, op, value, reason, evidence), `tiers` {A, B}, `segments` [{key, label, when: [{field, op, value}]}], `a_cap` {share_of_capacity}. Ops: `in`, `between`, `has_any`, `has_none`, `eq`. A rule with no evidence shows as Hypothesis.

Formula, ported from Account Desk `src/outbound/scoring.py` `fit` (the code, not its SPEC text): lifecycle `customer`, `open_opp` or `competitor` is X; an exclude that matches is X; a field with no data is left out of the score; below `MIN_KNOWN = 0.6` of positive weight known the company is Not judged; otherwise matched positive weight over known positive weight times 100, minus matched penalty weights, clamped 0 to 100, rounded; tier A at or above `tiers.A`, B at or above `tiers.B`, else C. A model-read field counts toward `known` and matching like any field, but an exclude only matches on vendor, CRM or person data. Not judged is shown as its own state, never as C, and `scored_out_of` (known weight over total) is shown beside every score.

Segments: first segment whose `when` all match, else `outside`. The demo's segments: Fintech 120 to 499, Fintech 500 to 1,999, Software, Data infrastructure, Developer tools, Marketplaces (each 120 to 1,999 employees), Enterprise (the five profile industries at 2,000 or more), Small (the five at 20 to 119), Outside.

Publishing rescoring runs as a job in batches of 1,000 with progress on the page. What moves: for a draft against the published version, counts of tier changes (from, to), by owner and by segment, and the list, computed in a read-only transaction. Backtest card: tier mix, scored profile-only (lifecycle check skipped), for current customers, customers in the top quarter of ACV, closed-lost companies, churned customers and a fixed random control of 500. A cap: if tier A holds more accounts than the active plan's A capacity, A accounts beyond it (ranked by expected value) show as "A over capacity"; the tier itself is unchanged.

## 8. Sizing (`sizing.py`)

Per segment and per region group: companies; tier counts; not judged; public count and coverage (universe over public count, unknown where no public count); deal-size basis (median ACV and quartiles from won deals; under 15 won deals borrow the overall figures and say so); win-rate basis shrunk toward the overall rate, (wins + 20 x overall) / (opps + 20), with the raw rate's Wilson range beside it.

- TAM = A and B companies x ACV. Low: known-fit A and B x 25th percentile ACV. High: adds not-judged companies at the segment's known A-and-B share, x 75th percentile ACV.
- SAM = the TAM computation over companies in served regions (North America and Europe), not excluded, and reachable: the segment's signer persona findable in `reachability`.
- SOM (12 months) = min(SAM companies, companies the active plan can work in 12 months) x shrunk win rate range (Wilson low and high of the shrunk rate's basis) x ACV quartiles. Plan capacity counts accounts the active plan's people can carry at their tier hours for 12 months, shared across segments by the segment's share of SAM companies.

No single TAM number appears anywhere; every figure is a range with its parts one tap away.

## 9. Capacity, territories, handoffs, tests, proposals

### 9.1 Capacity and territories (`territories.py`)
Hours a month per account by tier from settings (A 1.0, B 0.4, C 0.1, X 0; labelled as our assumptions; decision 17 says why they differ from the plan's 4.0, 1.5 and 0.25). Each SDR or AE has `selling_hours_month` (default 100) times effective FTE; ramp is linear from 0 to 1 over `ramp_months` (default 3) from `started_on`. Assignment for a draft plan, in order: customers and open deals stay with their CRM owner (`existing_owner`, `open_deal`); territory rules (region groups, segments) choose the territory; inside a territory, A then B accounts, highest expected value first, go to the person with most spare hours while they have room (`rule`); a balancing pass moves the lowest-value accounts between people in a territory until each person's expected value is within 15% of the territory mean and nobody is over 100% of hours (`balance_move`), or reports that it cannot. A and B accounts left over are unassigned and form the hiring gap (accounts, hours, and people at 100 hours each). Expected value = shrunk segment win rate x segment median ACV x score / 100.

What changes before activation: accounts that change owner by person, and open deals that would cross owners (refused unless a `manual` assignment with a note). Activate: manager only, not the author; the old active plan is retired; every owner move is written to the audit log.

### 9.2 Handoffs (`handoff.py`)
Account Desk: `accounts.csv` with exactly `name,domain,industry,employees,country,revenue_band,tech,lifecycle,owner_email,crm_id,parent_domain` for tier A and B companies assigned in the active plan plus the worked group of any running test, never a held-back member, never a sole trader; and `icp.json` in Account Desk's shape using only `industry`, `employees`, `region`, `revenue_band`, `tech` (ops `in`, `between`, `has_any`, `has_none`; `eq` compiles to `in` with one value). Rules on other fields go to `dropped_rules` and the Handoffs page. Test: every exported company with every exported field known gets the same tier from a copy of Account Desk's formula on the exported ICP as Market Desk gives it, when no rule was dropped.

Events Desk: `icp.md` in the headings of `~/Developer/events-desk/samples/orrery-icp.md` (Seller, Owner, Last reviewed, The short version, Size, Where we win, How we tier a company, Who we talk to, Kinds of company we see, Who we skip, Companies we know, Looks right, is not). Mapping: A is tier 1, B is tier 2, C and X are tier 3. Each section is written by code from the published version. Test: every heading present, every number equals the profile's, every example's stated tier equals the mapping of its score.

Each book is versioned per destination with a diff against the previous book (added, removed, tier moved, owner moved). Downloads only; nothing is pushed. Results back: `desk_results` rows are written by a job (simulated in the demo; a CSV import and an HMAC-signed webhook for a real install).

### 9.3 Segment tests (`tests_seg.py`)
A draft test names a segment and a cohort size. Default cohort = (1 + 4) x `n_per_arm(0.10, 0.10)` from Account Desk's `stats.py`, rounded up to the next ten: 520. The form refuses a segment with fewer eligible companies (prospects at tier A, B or C, not in another running test), naming how many it has. Held back: 20%, by hash of test id and domain. Starting writes members and puts the worked group into the next Account Desk book. Read: meeting rate worked against held back with a Newcombe 90% interval; below the size `n_per_arm` needs, the page shows only "Needs N more accounts". Decisions: expand (creates a `segment_expand` proposal), drop, extend.

### 9.4 Proposals (`proposals.py`)
Code decides: a `clear_higher` finding whose value no rule covers becomes `add_rule`; `clear_lower` becomes a penalty, or an exclude when one loss code is above half its losses; a rule whose finding is `not_clear` or `explained_by_size` with at least 60 opportunities becomes `drop_rule`; a read segment test with a clear lift (Newcombe 90% low above 0) becomes `segment_expand`. The model only words a proposal. RevOps makes a proposal into draft changes or dismisses it with a reason (a manager can dismiss too). Publishing still needs a second person.

## 10. Statistics

Wilson 95% (pass `conf=0.95`; Account Desk's default is 90%); Newcombe hybrid score; Fisher exact two-sided (sum of hypergeometric probabilities no larger than the observed one, with a relative tolerance of 1e-7); Holm step-down; Mantel-Haenszel with Robins, Breslow and Greenland variance; median interval from binomial order statistics. Each has one function and one test against a published value. On screen: a rate with its range in small type ("38% (34 to 42)") and the opportunities beside it; verdict words with an icon: Clearly higher, Clearly lower, Not clear, Too few to tell, Explained by size. Never "p", "significant", "confidence interval", "Holm" or "odds ratio" on a screen. Cycle is on won deals only; the column says "Won deals".

## 11. AI tasks

Every task: one prompt with a version (hash), a schema, a stand-in for demo and tests, recordings per eval case, code gates; on a failed gate one rewrite with the failures given; on a second failure the output is withheld and the screen shows figures without words. Text given to the model sits between markers it cannot close and is described as data with no authority.

### 11.1 classify: read a company
Input: `{"company": {"name": str, "description": str}, "industries": [closed list], "pricing_models": ["usage", "seat", "transaction", "mixed"]}`.
Output: `{"industry": str, "industry_quote": str|null, "pricing_model": str, "pricing_quote": str|null, "instructions_in_text": bool}`; a label is from its list or `unknown`.
Gates: label in list or `unknown`; a quote is a verbatim substring of the description and present for every label other than `unknown`; stored with source `model`, never over a vendor, CRM or person value; can place a company in a segment, never exclude it.
Industries list: Software, Fintech, Data infrastructure, Developer tools, Marketplaces, Healthcare software, IT services, Agencies, E-commerce, Manufacturing, Education, Government, Media, Logistics.

### 11.2 loss_code: code a loss reason
Input: `{"kind": "loss"|"churn", "text": str, "competitors": [names]}`. Output: `{"code": one of price, timing, no_decision, competitor, missing_feature, compliance, champion_left, bad_fit, other, "competitor": str|null}`.
Gates: code in list; a competitor counts only if it is in the list and its name appears in the text, otherwise it is set to null.

### 11.3 segment_story: say why a segment buys
Input: `{"segment": {"key", "label"}, "figures": [{"id": str, "label": str, "value": str}], "quotes": [{"id": int, "kind": "reason_to_buy"|"objection"|"competitor", "text": str}]}`.
Output: `{"sentences": [{"text": str, "quote_ids": [int], "figure_ids": [str]}]}`, one to four sentences.
Gates: every quote id is among the inputs; every sentence cites at least one quote id; words inside quotation marks are a verbatim substring of a cited quote; every number in a sentence equals a provided figure value as written; no person or company name from the CRM or the team appears (checked against the database, and in evals against a list the case supplies to the grader only).

### 11.4 proposal_text: word a proposal
Input: `{"change": {"kind", "field", "field_label", "op", "value_label", "weight"}, "findings": [{"id": int, "trait": str, "value": str, "opportunities": int, "win_rate": str, "range": str, "rest_win_rate": str, "verdict": str, "top_loss": str|null}]}`.
Output: `{"describes": {"kind", "field", "value_label"}, "sentences": [{"text": str, "finding_ids": [int]}]}`, exactly two sentences.
Gates: `describes` equals the input change; the value label appears in the text; every number equals a figure of a cited finding as written; no trait value named that is not in the findings; never "the buyer needs", "they need" or "you need".

### 11.5 Evals
Written by an agent that never sees `src/`: 60 classify, 80 loss_code, 20 segment_story, 20 proposal_text cases in `evals/*.jsonl` and `evals/CASES.md`. Graded by code where code can see the answer, by a Claude Sonnet 5.5 judge with a written checklist where not. `make evals` replays recordings free and `tests/test_evals.py` runs that in CI and fails on a stale recording; `make evals-live` calls Claude with a $15 cap. Floors in `evals/thresholds.json`: safety measures at 100% (verbatim quotes, no invented competitor before the gate, hidden instructions ignored, and no shown story or proposal with a broken rule); the model's first-attempt rates for numbers, names and the change are reported beside what the gate caught; others sit a little under the results they were set from, set after those results.

## 12. Pages and side sheets

Pages: Market, Evidence, Profile, Accounts, Territories (tab Capacity), Tests, Changes, Handoffs, Sources, My book, Settings. Sheets: Segment, Finding, Company, Person, Profile version, Plan move, Test, Proposal, Book, Source. Everything that names a thing opens it; a sheet opened from another shows the way back; Esc, outside click, back and the close button close it. Phone (375): bottom bar Market, Accounts, Changes, More (RevOps and managers); My book, Accounts, More (SDRs and AEs). Every sentence a screen can show is in `docs/SCREEN-COPY.txt`; a test fails on a new one.

## 13. Security and compliance

SQL parameters everywhere; roles checked in the API for every write and every money field; no uploads in the public demo; CSV import limited to 5 MB and 50,000 rows in live mode; results webhook signed with HMAC SHA-256 and a timestamp within 5 minutes; MCP server read-only in a read-only transaction; secrets never logged; `AUTH_MODE=header` verifies Cloudflare Access's signed token and refuses unsigned headers. Call notes are redacted at import (CRM contact names and a name-pattern pass become the role in brackets); the original never enters the database; a test plants 50 names and requires none to reach the database. Team members are the only people stored; erasing one reassigns their accounts through a manual plan move with a note. Sole traders are excluded from every book. A source marked no redistribution cannot feed a book file. No LinkedIn scraping. The public demo holds only invented data.

## 14. Definition of done

1. PROJECT-STATUS lists gates 0 to 10 with a date and a result for each, and what was cut.
2. `make setup && make demo` builds the world and serves it at http://localhost:8800, or the live URL opens.
3. Market shows TAM, SAM and SOM as ranges, and DACH's SAM far below its TAM.
4. Evidence shows usage pricing as Clearly higher, 2,000 to 4,999 employees as Clearly lower, Salesforce as Explained by size, Brazil as Too few to tell, and nothing for HQ city.
5. Profile's draft v4 shows what moves before publish, and its author cannot publish it.
6. Territories shows hours against capacity per person and the hiring gap; the Q1 draft can be activated by Elena, not by Sam.
7. Handoffs offers an Account Desk CSV and ICP that list usage pricing as a dropped rule (from the draft), and an Events Desk document in its format.
8. `make test` passes on Postgres 18, including scenario coverage, rules against data, screen copy and statistics against known values.
9. README's "What is real and what is simulated" names P1 to P8, and the AI table shows real numbers or says "not run live".
10. No em or en dash anywhere in the repo.

## 14a. Corrections from gates 1 to 6 (2026-11-12)

- Only a manager publishes a profile version, and never its author (gate 1).
- Evidence: the Holm family is every trait value with at least 30 deals, including values later called Too few because they have under 5 wins, and each rule of the published profile is tested as a trait of its own (deals matching the rule against the rest).
- `loss_code` has no rewrite: its gate clears an unsupported competitor and maps an unknown code to `other`; there is no prose to withhold.
- Sizing also has a `total` row; region rows and Outside use the overall signer; the account-to-opportunity rate is the segment's own from 100 worked accounts, else the overall rate, else the `opp_rate_default` setting before any results exist.
- An "expand" decision needs a clear difference, and only an expanded test makes a `segment_expand` proposal.
- A licence that forbids redistribution blanks the affected cells in every file (books, the Events Desk document, the world export) rather than refusing the book (decision 27).
- Writes take JSON only (a cross-site form cannot send it); the results webhook validates rows, reads a delivery once and accepts held-back rows and a test id; `python -m market import-results FILE` reads the same rows from a CSV (5 MB, 50,000 rows).
- `MODE=live` refuses to start without `AUTH_MODE=header`. Erasure is `POST /api/users/{id}/erase` and `POST /api/companies/{id}/erase-notes` (refused on the public demo).
- The demo is built in date order, so a book, a plan or a test never knows what happened after its date; tests and books exclude companies with a deal open or a customer contract on their own date.
- A tier A prospect in our regions with no owner shows on Accounts as "A over capacity".

## 15. Gate 0 corrections (2026-11-11, fresh Opus reviewer: 1 blocker, 9 majors, 7 nits)

These override the sections above where they differ.

1. **SOM (blocker).** Win rate is per opportunity and capacity counts accounts. SOM = min(SAM companies, plan capacity accounts) x account-to-opportunity rate x win rate x ACV. The account-to-opportunity rate is opportunities per worked account over 12 months from `desk_results` (worked groups only), overall when a segment has under 100 worked accounts. Plan capacity accounts = accounts the plan's people can hold at once at their tier hours, times 12 / `account_cycle_months` (default 3: an account is worked for a quarter), shared by segments in proportion to SAM companies.
2. **Ranges are scenario bounds.** Low = the low end of every part multiplied; high = the high end of every part. Win-rate bounds are the Wilson 95% interval on pseudo-counts (wins + k x overall, opps + k). ACV bounds are the 25th and 75th percentiles of won deals. README and DECISIONS call these scenario bounds, not a statistical interval.
3. **Size check needs attenuation.** Explained by size needs both: the Mantel-Haenszel 95% interval includes 1, and the adjusted log odds ratio is at most half the crude one. Strata with no opportunities on either side are skipped. Traits nested in size (size band, segment) are not size-checked.
4. **Holm family.** Only trait values with at least 30 opportunities are in the family (a filter on counts, not outcomes); smaller values are Too few to tell and are not counted. HQ city is tested for the 12 cities with the most opportunities in the window. The world plants at least 120 opportunities in the window for P2 and P3.
5. **Exact held-back split.** Members are ranked by hash of test id and domain; the lowest round(0.2 x cohort) are held back. A cohort of 520 holds back exactly 104.
6. **Tests take A and B only.** Eligible = prospects at tier A or B under the published profile, in a served region, not in another running or read test, and not in an Account Desk book of the last 180 days (found by the rules-against-data audit: an account already worked is not a clean comparison). Account Desk works only A and B.
7. **Model-read values do not travel.** Exported CSV cells come only from vendor, CRM or person values; a model-read value is left blank, so Account Desk cannot apply an exclude on it. `region` follows Account Desk's `region_of`.
8. **Dropped rules from a draft.** Books are versioned from the published profile. Handoffs also offers a preview from any draft (not versioned, downloadable) listing that draft's dropped rules; draft v4's preview lists usage pricing.
9. **Proposal noise.** A `clear_lower` value is proposed only when no other value of the same trait is proposed as `add_rule` (the add covers it) and at least 10% of companies with that value reach A or B under the published profile. The rest of a value never includes unknowns. `segment_expand` proposes a factor `segment in [key]` with weight 10, which cannot travel to Account Desk and is listed as dropped.
10. **Third test named.** The running test is Data infrastructure, started 2026-10-01, ending 2027-01-31.
11. **Nits.** Account Desk's size factor is 120 to 2,000 inclusive and is kept; a company of exactly 2,000 sits in the 2,000 to 4,999 band and no segment's sweet spot. Reachable = `has_named_contact_source` true for the signer persona; for region rows and Outside the signer is the overall most common signer on won deals. `a_cap` is not used; the A cap uses the active plan's A capacity. Not judged differs from Account Desk, which shows such a company as C with score 0 (decision 12).
