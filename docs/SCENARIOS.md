# Scenarios the demo must hold

Every scenario the spec promises. `tests/test_scenarios.py` asserts each one exists in the demo database and writes `docs/SCENARIO-COVERAGE.md` (scenario, where it shows, how many). A missing scenario fails the build.

| Key | Scenario | Where it shows |
|---|---|---|
| P1 | Usage pricing is Clearly higher, an `add_rule` proposal exists, and the Account Desk book lists it as a dropped rule | Evidence, Changes, Handoffs |
| P2 | 2,000 to 4,999 employees is Clearly lower with a longer won-deal cycle, and a penalty is proposed | Evidence, Changes |
| P3 | Healthcare software is Clearly lower with compliance above half its losses, and an exclude is proposed | Evidence, Finding sheet, Changes |
| P4 | Salesforce is Explained by size | Evidence |
| P5 | Brazil is Too few to tell (9 opportunities, 5 won, all marketplaces) and no proposal names it | Evidence, Finding sheet |
| P6 | DACH's SAM is far below its TAM (high end under half) | Market, by region |
| P7a | The fintech 120 to 499 test is read with a clear lift and a `segment_expand` proposal | Tests, Changes |
| P7b | The developer tools test is read with no clear difference | Tests |
| P8 | No HQ city or founding period finding is clear | Evidence |
| S1 | Draft v4 has companies that move tier against v3 | Profile |
| S2 | A plan with someone over capacity, or a hiring gap above zero | Territories, Capacity |
| S3 | A manual move with a note | Territories, Plan move sheet |
| S4 | A held-back company refused from an Account Desk book | Tests, audit log |
| S5 | A not-judged company | Accounts, Company sheet |
| S6 | A model-read field that could not exclude a company | Company sheet |
| S7 | A withheld segment story | Market, Segment sheet |
| S8 | A proposal dismissed with a reason | Changes |
| S9 | A test too small to read | Tests |
| S10 | A source that missed its run | Sources |
| S11 | One running test and one read test | Tests |
| S12 | Draft v4's author cannot publish it | Profile |
| S13 | The Q1 draft plan cannot be activated by its author | Territories |
