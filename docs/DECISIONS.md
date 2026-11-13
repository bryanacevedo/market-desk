# Decisions

Numbered. Each says what was decided, why, and what it costs.

## 1. Companies and roles, never named prospects
**What:** the desk stores companies, deal roles as persona and seniority, and redacted call notes. No prospect's name, email or phone enters the database. **Why:** a market tool does not need people; keeping them out leaves GDPR Article 14 notices and CCPA requests with the desks that contact people. **Cost:** buying-committee maps are by role, not by name, and a note's speaker is a role.

## 2. Account Desk's fit formula, ported from its code, not its spec text
**What:** fit is Account Desk's `scoring.fit` (lifecycle X, excludes, known-weight share, MIN_KNOWN 0.6, penalties, the profile's own tiers), plus an `eq` operator. Account Desk's SPEC sections 6 and 22.7 say tiers at A 70 and B 50 and show no penalties key; its `catalog.py` and `scoring.py` use penalties and tiers 85 and 65. The code is what runs, so the code was ported. **Why:** a company Market Desk calls A must be A in Account Desk. **Cost:** the port is a copy; if Account Desk's formula changes, the equivalence test (in `tests/test_handoff.py`) holds Market Desk's copy of that formula, not Account Desk's live code.

## 3. Ranges, not points
**What:** every sizing figure and every rate is shown as a range; no single TAM number exists on any screen. **Why:** a TAM point estimate claims a precision the inputs do not have. **Cost:** figures take more room and need a tap to see their parts.

## 4. The size check
**What:** every clear finding is checked within size bands with a Mantel-Haenszel odds ratio; if its 95% interval includes 1 and the effect shrinks by at least half (decision 15), the verdict is Explained by size. **Why:** size drives most B2B win rates, so a trait that only travels with size would otherwise become a rule. **Cost:** a real effect that is also concentrated in one size band can be called Explained by size; the finding still shows its crude figures.

## 5. Two people to publish a profile or activate a plan
**What:** the database refuses a profile published by its author and a plan activated by its author. **Why:** the profile decides every account's tier and owner; one person should not change it alone (Account Desk does the same for play launches). **Cost:** a desk with one RevOps person and no manager cannot publish; the plan's single-person exception was not built.

## 6. Win rates shrunk toward the overall rate for sizing
**What:** sizing and expected value use (wins + 20 x overall) / (opps + 20). The constant is a setting. **Why:** a segment with 9 deals and 5 wins would otherwise carry a 56% win rate into SOM. **Cost:** a small segment that really is better looks closer to average until it has deals.

## 7. Capacity in hours per account per month
**What:** A 1.0, B 0.4, C 0.1, X 0 hours a month per account (decision 17); 100 selling hours a month per SDR and 40 per AE for account work (RevOps and the manager carry none); ramp linear over 3 months (Bridge Group 2025 average). These are our assumptions, labelled as such on the Capacity tab and in Settings. **Why:** size any channel by throughput times window times seats. **Cost:** the hours per tier are invented; a real team sets them.

## 8. Statistics copied from Account Desk, then extended
**What:** `stats.py` copies Account Desk's `wilson`, `newcombe`, `n_per_arm` and `fisher_greater` (intervals default to 90%), then adds a two-sided Fisher exact test, Holm, Mantel-Haenszel and a median interval. Every evidence call passes `conf=0.95` explicitly; segment tests use 90%, as Account Desk's play tests do. **Why:** one method across the desks; evidence about the profile is held to a stricter level than a test of a play. **Cost:** two levels in one product, stated in README.

## 9. RevOps role key is `revops`, not `gtm`
**What:** Account Desk calls Sam's role `gtm`; here it is `revops`. **Why:** this desk's owner is revenue operations. **Cost:** an install shared across desks maps the role.

## 10. Events Desk tier mapping
**What:** A is tier 1, B is tier 2, C and X are tier 3, written into the Events Desk document and checked by a test. **Why:** Events Desk tiers in prose by rules, not by weighted scores. **Cost:** a company near a boundary may read differently in Events Desk's own parser, which is untested on this file.

## 11. The world is exported for the other desks, with people only in the export
**What:** a stable export of companies, invented people and tiers, keyed by ids derived from domains, is the shared world's source for Account Desk and Events Desk later. People are generated from the seed at export time and never enter Market Desk's database. **Why:** Bryan asked for one universe across the desks (2026-11-11), and decision 1 keeps named people out of this desk. **Cost:** the people file is not a table anyone can query here; changing the generator changes the people, so the format carries a version.

## 12. Not judged is its own state
**What:** a company with under 60% of the profile's weight known shows as Not judged, not as C. Account Desk's code returns C with score 0 for the same company. **Why:** a gap is a third state, neither good nor bad; counting it as C hides how much of a segment is unknown, which sizing needs. **Cost:** the two desks show the same company differently; the handoff sends only A and B, so no exported tier differs.

## 13. Sizing ranges are scenario bounds
**What:** TAM, SAM and SOM low and high multiply the low ends and the high ends of their parts (ACV quartiles, Wilson bounds on the shrunk win rate, the account-to-opportunity rate). **Why:** the parts are not independent estimates, and a combined interval would need a model of how they move together that the data cannot support. **Cost:** the ranges are wide and are not confidence intervals; README says so.

## 14. SOM counts opportunities, not accounts
**What:** SOM multiplies worked accounts by the share that became opportunities before applying win rate. **Why:** gate 0 found the plan's formula treated every worked account as an opportunity, inflating SOM five to ten times. **Cost:** SOM depends on desk results; a desk with none uses the overall rate.

## 15. Explained by size needs the effect to shrink
**What:** a clear finding becomes Explained by size only when the size-adjusted interval includes 1 and the adjusted effect is at most half the crude one. **Why:** an interval that includes 1 can also mean too little data within bands; that is not confounding. **Cost:** a weak confounder that shrinks by less than half stays clear.

## 16. Only values with 30 opportunities are tested
**What:** the Holm family counts trait values with at least 30 opportunities; HQ city is tested for its 12 largest cities. **Why:** values that can never be clear only cost power; filtering by count does not look at outcomes. **Cost:** a value under 30 opportunities is never a rule, however lopsided.

## 17. Hours per account cut to a quarter of the plan's defaults
**What:** A 1.0, B 0.4, C 0.1 hours a month per worked account, and an account is worked for one quarter (four turns a year), instead of the plan's A 4.0, B 1.5, C 0.25 held all year. **Why:** at the plan's figures four SDRs hold 25 A accounts each, which contradicts the plan's own demo (about 1,100 accounts in Account Desk's last two books) and made the hiring gap read as hundreds of people and SOM as about $100,000 a year. Account Desk does the research and the drafting, so an SDR's hours per account are closer to an hour a month. The plan already marked these as invented assumptions for RevOps to edit. **Cost:** still invented; a real team measures its own hours per account.

## 18. Brazil shows as a country, not as a pair of traits
**What:** evidence tests single traits; Brazil's 9 deals (all marketplaces, 5 won) show as the country Brazil, Too few to tell, and its sheet lists the marketplaces behind it. **Why:** testing every pair of traits would multiply the values tested by a hundred and leave the correction nothing to find. **Cost:** a real effect that lives only in a pair of traits is found only if one trait carries it.

## 19. Sizing by region as well as by segment
**What:** sizing rows exist for each segment, each region group and the whole market. **Why:** reachability differs by region (P6, DACH), and a segment row cannot show that. **Cost:** two tables to read on Market, behind one switch.

## 20. A rule explained by size is proposed for removal
**What:** a factor or penalty of the published profile (never an exclude) whose own finding is Not clear or Explained by size, with at least 60 deals, becomes a drop proposal. The plan named only Not clear. **Why:** a rule that only travels with size double counts the size rule. **Cost:** more proposals; the region rule's drop proposal is dismissed in the demo with the reason a sales leader would give.

## 21. Expected value
**What:** shrunk segment win rate times the segment's median won deal times the fit score over 100. **Why:** the plan said "shrunk win rate times ACV for the account's segment and tier"; tiers within a segment have too few deals to carry their own rates, so the score stands in for the tier. **Cost:** expected value ranks accounts; it is not a forecast.

## 22. The buyer's own words are what the note puts in quotation marks
**What:** quotes are the spans a call note puts in quotation marks; a won deal gives reasons to buy, a lost one objections, a competitor's name makes it a competitor quote. **Why:** the plan has no extraction task among its four, and a quote must be verbatim. **Cost:** notes without quotation marks give no quotes.

## 23. The demo's AI is a stand-in; live answers are in the evals
**What:** the demo builds with deterministic stand-ins written in code (`src/market/sim_llm.py`); live Claude answers exist only in the eval recordings. **Why:** the image is built without keys, and the same seed must build the same rows. **Cost:** the words on the demo's screens were written by code that imitates the shape of the model's answers, not by Claude; README says so.

## 24. A running test's accounts are worked however full the book
**What:** when a test starts, its worked accounts join the active plan with their territory's lead, and a new draft plan keeps them, even past 100% of hours. **Why:** dropping them would end the test; a test is a deliberate spend. **Cost:** Tom and Priya read over capacity on the Capacity tab while the data infrastructure test runs.

## 25. Recently worked accounts are not test material
**What:** a test excludes companies in an Account Desk book of the last 180 days. Found by the rules-against-data audit: 18 companies held back in the October test had been in July's book. **Why:** an account already worked is neither a clean worked account nor a clean comparison. **Cost:** fewer eligible companies; the demo world has more data infrastructure companies so its test still fits.

## 26. The held-back meeting rate in the finished tests is 10.6%
**What:** the world gives the finished tests' held-back groups 11 meetings out of 104 rather than 10. **Why:** Account Desk's reading recomputes the sample it needs from the held-back rate it sees; at 9.6% it asks for 107 held-back accounts and the 520-account test could not be read. Gate 0 predicted this. The world was tuned, not the rule. **Cost:** a test that lands just under its design rate reads as needing more accounts.

## 27. A restricted licence blanks cells, it does not refuse the book
**What:** a value whose only source forbids redistribution is left blank in every file the desk writes; the rest of the row ships. **Why:** refusing the whole book over one vendor's field would stop every handoff; a blank cell is a gap Account Desk already handles (it leaves unknown fields out of the score). **Cost:** a book can carry a company whose most useful field is blank.

## 28. The world export is the demo's only
**What:** `world-export` refuses unless the desk is in demo mode, leaves sole traders out, and applies the same licence and model-read rules as a book. The people in it are invented at export time. Whoever loads it into a desk that contacts people takes on that desk's duties to them; this desk stores none. **Why:** on live data it would invent people at real employers. **Cost:** the shared world stays a demo universe until the other desks have their own people data.

## 29. Writes take JSON, and an unchosen visitor is an SDR
**What:** every write must arrive as JSON, and a request that names no user acts as the first SDR; the web app opens a first visit as RevOps by choice. **Why:** the security review: a cross-site form cannot send JSON, and the least-privileged default never shows company money by accident. **Cost:** a script that posts forms must send JSON.

## 30. Market Desk's own look: ochre, Archivo, ranges as intervals
**What:** ochre `#A2671F` is the accent and the halo; Archivo semi-condensed is the display type; steel blue `#3E6A8A` is the waiting status; ranges are drawn as intervals and the market as a field of tiles (`docs/DESIGN-CHECKLIST.md`, "Spirit"). **Why:** Bryan, 2026-11-12: v1 was too close to Account Desk; each desk shares the bones and keeps its own spirit (Events Desk green, Account Desk cobalt). Amber is the waiting colour in the other desks and sits next to ochre, so waiting moved to steel blue. **Cost:** a status colour that differs from the sister desks; a reader moving between them learns one new colour.

## 31. Capacity follows SAM, and what a segment cannot use passes on

SPEC 15.1 shares the plan's 12-month capacity among the segments its territories cover in proportion to their tier A and B companies in SAM. A segment can never work more companies than its SAM; what it cannot use passes to the covered segments with room, so no capacity is lost to the cap. A segment no territory covers gets none, and Market says "No capacity" there rather than a zero market. Region rows are a second view of the same capacity, shared by each region's SAM and priced at the overall rates; they are not a split of the segment rows, so they do not add up to the total (the README glossary says so).

## 32. The share that becomes a deal counts only full stretches of Account Desk work

The opportunity rate behind SOM and expected value is the share of Account Desk's worked accounts, over periods of 60 days or more in the last year, that opened a deal. A running test's first weeks and Events Desk's one-day results are left out: they measure something else. A segment uses its own rate from 100 such accounts, otherwise the overall rate; before any results exist, the default in settings, shown as an assumption.

## 33. Expected value is a 12-month figure on the same basis as SOM

Per account, expected value is the share that becomes a deal, times the segment's planning win rate, times its deal size, times the fit score over 100. The first layer reviewers found per-person expected value larger than the company's SOM, because it left out the share that becomes a deal; it now includes it, so a person's figure is a share of what the plan can win, not every account a deal.

## 34. A finished test hands its accounts back

When a test is read, its worked accounts leave every live plan, and the next plan places them by its rules. A test's held-back accounts leave every live plan the day the test starts. A plan is built from what was true on the day it was drafted: a company that became a customer, or opened a deal, after that day is still a prospect in that plan.

## 35. Who moves and who erases

Only RevOps moves an account by hand, in a draft plan, with a note; the manager reviews and activates. RevOps or a manager may erase a team member or a company's notes. Erasing a person also scrubs their name from the audit log and from move notes; erasing a company's notes withholds any segment story that quoted them and clears the stored model output that held the quote.

## 36. What the layer reviews left as it was

The Events Desk document keeps the heading "Looks right, is not", because Events Desk's parser reads it by name. The `?as=` parameter that picks the acting person stays on the public demo only, for links and screenshots; a live install takes identity from the access header alone. The demo's 14 SDR-owned accounts that opened deals with an AE after the active plan was drafted stay as they are: the plan shows them under "What changes" until the next plan.

## 37. Second design pass: the signature carries every decision page

A fresh designer compared every screen with Account Desk and Events Desk, and a fresh editor read every visible string. What changed, and why:

- Capacity is a range, not a bar: the band is the hours a person holds today, a dashed stretch the hours still to come while they ramp, and the tick the hours their book needs. Over is a tick past the band.
- A draft plan is read against the active one: each headline figure says what it is now and the change, each person's A and B accounts are drawn as a ring (now) and a tick (draft) on one scale, What changes sits right under the figures, and Activate is in the head row.
- My book draws each account's score against the tier lines (a fit band), with column heads; the reason shows only when it says something (a hand move, a test).
- A test's two meeting rates are two ranges on one track: worked in ochre, held back in steel.
- The tile field's shade is the tier A share scaled across the segments shown, so it encodes something; narrow tiles keep their names whole.
- Bars that are not intervals (what moves, hours, fields known) step back to half-strength ink; the tier mix is drawn in ochre tones.
- Badges count the reader's own work: open changes for RevOps; a draft to publish and a plan to activate for the manager.
- A button you cannot press yet is a quiet outline; Publish shows only to someone who can publish.
- Copy: 38 tells removed (an explainer tagline, cute nav groups, one name each for changes, ICP, rules not sent to Account Desk, capacity and data known; stand-in sentences that repeated the figures beside them).

Kept as Bryan liked them: Market's TAM, SAM and SOM rows, Evidence's bands and the tier-mix table (now with v3 beside v4).

## 38. Every range explains itself, and every term has a tip

Bryan could not read the market ranges, and he is the best-informed reader the screens will get. Each range now says what it is on the line (TAM, SAM, SOM), writes its low and high, and sits under a named scale (money marks are powers of ten; rates run 0% to 60%, tests 0% to 30%). Market, Evidence and Changes carry a key drawn the way the marks look. One Tip component explains figures, column heads, section titles, sheet terms and status words from one dictionary (`web/src/tips.ts`), on hover and on keyboard focus; inside a pressable row it does not take focus of its own. A fresh reviewer who had never seen the product read every page as a sales leader twice; the first read found 49 unexplained items, the second 11, all fixed or explained. The help cursor is not used, at Bryan's request. Settings show shares as percentages. Text links are quiet buttons.

## 39. Sellers do not use Market Desk

Bryan's call for SDRs, then for AEs. Market Desk is for the people who plan the market: two roles sign in, RevOps and the manager, and a visitor who has not chosen reads as the manager. SDRs and AEs stay in the data as people in territories. Each seller's book, with every account's tier, segment, fit score and owner, is meant to go to CRM Desk (not built yet; Market Desk has no CRM Desk adapter), and Account Desk gets the one book file Market Desk already writes (every assigned account with its owner, downloaded, not imported yet), so sellers see the result where they work. The API refuses a seller and the demo does not offer one. My book and the trimmed seller views, with their tests, are gone; decision 29's unchosen visitor (an SDR) no longer applies. Territories says it in one line.

## 40. The market comes from the shared world

`sim/lumen.py` loads the companies, history, customers, call notes, coverage and team from the slice of `lumen-world` vendored in `world/`; `sim/world.py` stays as the rollback (`WORLD=legacy`). The companies are this desk's own, drawn the same way (lumen-world reproduces its draws; 27 carrying the seller's name are renamed). The team is the one roster: Leah Ahn joins Tom on North America's data, developer tools, marketplaces and small companies, and Europe splits between Priya and Hannah (UK, Ireland, France, Benelux, Nordics) and Jonas and Lukas (DACH and the south). Deals are the world's, moved into working hours and cut at 13 August 2026, then played to now as the world plans them; amounts are the US dollar amount at the close. Call notes arrive with the names they mention and are redacted before anything is stored (decision 1). With six SDRs working books, the data infrastructure test that starts on 1 October finds 476 companies free of recent books against the 520 its power needs; it runs on 460, with less power, which the Tests page shows. Why: one story across the desks. Cost: figures moved (P1 314 deals, P3 183, P4 699; `docs/SCENARIO-COVERAGE.md`), every planted relationship still found.

## 41. Books go to a CRM when one is set

With `CRM=crmdesk`, activating a plan queues every assigned account (name and vendor firmographics, tier, segment, fit score, profile version, the AE who owns it and the SDR who works it) in `crm_outbox`, in the activation's own transaction, 100 accounts to a row; a job sends each to CRM Desk's `POST /api/v1/accounts/batch` and keeps the answer. A timeout, a refused connection or a 5xx leaves the row queued; a 429 waits as long as CRM Desk asks. Handoffs lists what was sent and every refusal, such as an SDR a manager pinned in CRM Desk. `python -m market crm-sync` sends the active plan now. Unset, nothing is queued: the desk exports files and works alone (shared-world DESIGN.md 2a). The demo replays one recorded exchange (`world/journal.jsonl`, made by `lumen-world/stage/rehearse.py`) instead of calling CRM Desk. Migration 0002. Cost: a full book is one request per 100 accounts and CRM Desk counts each account against its limit, so a large plan takes minutes to land.

## 42. Links to the other desks only when told

`DESK_LINKS` (`crm_desk=https://...`) adds "Open in CRM Desk" on a company sheet and wakes the linked desk's service when a page loads; unset, Market Desk links to nothing and calls nothing. `/go/account/world:<id>` (or `domain:`) opens a company sheet for the other desks' links.

## 43. Territory moves are proposed, decided, then planned

A manager or RevOps person proposes moving accounts (up to 200) to an AE or SDR, optionally into a territory, with a reason and an effective date. A different person decides: a manager decides RevOps proposals; RevOps or another manager decides a manager's. The decision, who and when, is kept (`move_proposals`). An approval drafts a plan that is a copy of the active plan with only those accounts moved (reason `manual`, the reason as the note), so activating it changes exactly those accounts. Activation is the usual one: a manager other than the author, with the same CRM books. A move plan remembers the plan it was copied from and refuses to activate if the active plan has changed since. Not built: moving by territory rule rather than by account list.

## 44. Confirm before Publish ICP and Activate plan, and a way back

Both open a sheet that states in counts what will change: for Activate, accounts changing owner, open deals leaving their owner, who gains and loses, and requests to CRM Desk (none without a CRM); for Publish, rules changed, companies rescored, tier changes, and that nothing goes to CRM Desk until the next plan is activated. Roll back re-publishes the version the published one replaced, or reactivates the plan the active one replaced. Each is recorded (who, when) and shown under History. The restored version or plan keeps its original two-person approval. A plan rollback cancels batches still waiting, queues the earlier plan's books, and says plainly that batches CRM Desk already took stay taken until those books overwrite them; owners pinned in CRM Desk stay as they are. The plan's start date only affects capacity, not when owners change; the Activate sheet says so when the date is in the future.
