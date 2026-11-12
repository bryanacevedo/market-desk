# AI evals: results

Spent in all: $2.02 over 4 live runs, against a $15 cap.

| Task | Measure | Result | Cases | Floor |
|---|---|---|---|---|
| classify | industry accuracy | 97% | 60 | 95% |
| classify | pricing accuracy | 92% | 60 | 90% |
| classify | unknown when unsupported | 89% | 55 | 85% |
| classify | verbatim citations | 100% | 60 | 100% |
| classify | hidden instructions ignored | 100% | 9 | 100% |
| classify | instructions flagged right | 100% | 60 | 95% |
| loss_code | agreement | 94% | 80 | 90% |
| loss_code | competitor never invented | 100% | 80 | 100% |
| loss_code | competitor never invented after gate | 100% | 80 |  |
| loss_code | competitor matches | 99% | 80 | 95% |
| segment_story | shown | 100% | 20 | 95% |
| segment_story | judge faithful | 95% | 20 | 75% |
| segment_story | numbers match | 95% | 20 | 90% |
| segment_story | no names | 100% | 20 | 95% |
| segment_story | first attempt caught by gate | 5% | 20 |  |
| segment_story | shown with a broken rule | 0% | 20 | at most 0% |
| proposal_text | shown | 100% | 20 | 95% |
| proposal_text | judge faithful | 95% | 20 | 80% |
| proposal_text | numbers match | 100% | 20 | 90% |
| proposal_text | change matches | 95% | 20 | 90% |
| proposal_text | first attempt caught by gate | 5% | 20 |  |
| proposal_text | shown with a broken rule | 0% | 20 | at most 0% |

## Runs

1. all: $1.15. First run. Judge-faithful 35% (stories) and 55% (proposals).
2. segment_story,proposal_text: $0.57. After the story prompt fix and judge context: 85% and 75%.
3. proposal_text: $0.20. Proposal prompt told its inputs are data: 90%.
4. all, filling gaps only: $0.10. Judge checklist adds the cases' traps and sees each sentence's citations; first-attempt scoring. Model answers replayed; only the judge called.

Rows under 30 cases are a small sample: on 20 cases, one case is 5 points. The judge is Claude Sonnet 5.5 with a written checklist, a different model from the one under test (Claude Opus 5.5); it has not been checked against human labels. The floors other than the safety ones were set after the results, a little under them.
