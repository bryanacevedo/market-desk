# AI evals: results

Source: live Claude calls, recorded. Spent in all: $1.92 over three live runs, against a $15 cap.

| Task | Cases run | Not run | Measure | Result | Floor |
|---|---|---|---|---|---|
| classify | 60 | 0 | industry accuracy | 97% | 95% |
| classify | 60 | 0 | pricing accuracy | 92% | 90% |
| classify | 60 | 0 | unknown when unsupported | 89% | 85% |
| classify | 60 | 0 | verbatim citations | 100% | 100% |
| classify | 60 | 0 | hidden instructions ignored | 100% | 100% |
| loss_code | 80 | 0 | agreement | 94% | 90% |
| loss_code | 80 | 0 | competitor never invented | 100% | 100% |
| loss_code | 80 | 0 | competitor never invented before gate | 100% |  |
| loss_code | 80 | 0 | competitor matches | 99% | 95% |
| segment_story | 20 | 0 | shown | 100% | 95% |
| segment_story | 20 | 0 | judge faithful | 85% | 80% |
| segment_story | 20 | 0 | numbers match | 100% | 100% |
| segment_story | 20 | 0 | no names | 100% | 100% |
| proposal_text | 20 | 0 | shown | 100% | 95% |
| proposal_text | 20 | 0 | judge faithful | 90% | 85% |
| proposal_text | 20 | 0 | numbers match | 100% | 100% |
| proposal_text | 20 | 0 | change matches | 100% | 100% |

## Runs

1. 2026-11-12, all 180 cases, $1.15. Judge-faithful was 35% for segment stories and 55% for proposal wording (`REPORT-first-run.md`). The judge's reasons: stories ranked objections, gave advice, tied figures to quotes as cause and spoke for a whole segment from one quote; for proposals the judge had not been told the text describes a change to a profile.
2. The story prompt was told not to do those four things, and the judge was given the context of each text. Stories and proposals rerun: $0.57; 85% and 75%.
3. After the security review, the proposal prompt was told its inputs are data, which changed the prompt: proposals rerun, $0.20; 90%.

Floors (`thresholds.json`): the safety floors are 100%; the others sit a little under the result they were set from. The judge changed between runs 1 and 2, so the first run's figures are not comparable with the later ones.
