# Evaluation report

> Built from committed recordings. Reproduce every number below with no API key:
> `uv run python -m evals.suites.accuracy --model claude-sonnet-5-5` (or `claude-haiku-4-5`;
> add `--prompt v1` for the earlier prompt).

**Date:** 2026-11-05 · **Prompt:** `classify/v2@6f7324f773b3` · **Generator:** 0.4.0, seed 42,
2,000 claims · **Baseline fit:** seed 7 · **Confidence floor:** 0.0 (chosen from the sweep)

## Headline

| | Sonnet 5.5 | Haiku 4.5 | CARC lookup | Always abstain |
|---|---|---|---|---|
| Action accuracy | **67.2%** | 57.9% | 47.0% | 25.1% |
| **Wrong actions** (asserted, and wrong) | **0** | 35 | 44 | 0 |
| Missed handoffs (asserted where a person should decide) | **0** | 23 | 0 | 0 |
| Needless handoffs (abstained when evidence settled it) | 60 | 19 | 53 | 137 |
| USD per claim | $0.0063 | $0.0026 | $0 | $0 |

183 cases: the denials the rules lane hands to a human (14% of denied lines), each with a
synthetic case file. Pipeline-wide, 86% of denials get a rules proposal with zero model
spend.

**Sonnet asserts nothing wrong.** All 60 of its misses are handoffs, concentrated where it
often names the right action in its rationale and then defers: units over authorization
without an extension (17), bundling (24), unsupported medical necessity (9). **Haiku is
cheaper and asserts more, and 35 assertions are wrong** — 28 of them appeals against denials
its own evidence supports. In this domain a wrong appeal costs money and credibility with a
state payer; a needless handoff costs a reviewer a minute (ADR-031).

## Prompt v1 → v2

v2 is the author's edit of v1: it drops "when unsure, choose needs_human" and adds "if a
retroactive change was made after adjudication, suggest the next step, mark needs_human and
hand it off". The author's draft also put a confidence threshold (< 0.9) in the prompt; it
was moved to code instead (below).

| | Sonnet v1 | Sonnet v2 | Haiku v1 | Haiku v2 |
|---|---|---|---|---|
| Accuracy | 44.3% | **67.2%** | 50.8% | 57.9% |
| Wrong actions | 0 | **0** | 31 | 35 |
| Missed handoffs | 33 | **0** | 39 | 23 |
| Retroactive reinstatement | 0/33 | **33/33** | 0/33 | 17/33 |

The same edit made Sonnet better or equal on every row and made Haiku assert more wrong
actions.
Prompt changes do not transfer between models for free; each is measured per model.

## Confidence floor — in code, swept for free

A model's stated confidence is not calibrated, so the threshold below which an action
becomes a handoff lives in `routing/confidence.py`, and the eval re-scores the recorded
answers at each floor without new calls:

| Floor | Sonnet v2 acc. / wrong | Haiku v2 acc. / wrong |
|---|---|---|
| 0.0 | 67.2% / 0 | 57.9% / 35 |
| 0.8 | 55.7% / 0 | 58.5% / 23 |
| 0.9 | 25.7% / 0 | 54.6% / 14 |

For Sonnet no floor helps: at 0.9 it collapses to the always-abstain baseline, which is what
the 0.9 threshold in the prompt draft would have done. For Haiku a floor trades accuracy for
safety but never reaches zero wrong actions. Sonnet at floor 0.0 is the default.

## Run history

| Run | What changed | Sonnet acc. | Finding |
|---|---|---|---|
| 1 | first live run, generator 0.2.0 | 33.3% | Eval defects, not model defects: member ID missing from the input; visits clamped at midnight no longer matched billed units (the model caught it); replay keys ignored input data. [Details](../evals/history/2026-11-05-run1-sonnet-v1-gen0.2.0/README.md) |
| 2 | fixes above; paid services added for bundling (0.4.0) | 44.3% | Over-abstention traced to the prompt's "when unsure, choose needs_human"; retro-reinstatement policy missing from the prompt. Accuracy ranked Sonnet below Haiku despite Haiku's 31 wrong actions, which led to error types (ADR-031). |
| 3 | prompt v2 (author); confidence floor moved to code | **67.2%** | 0 wrong, 0 missed. The same edit made Haiku more wrong (31 → 35). |

Total API spend for all three runs: about $4.40.

## Honest limits

- The case files and the prompt are written by the same people, so this measures whether a
  model reads the evidence, not whether it copes with a real case file (ADR-029).
- One recorded run per model per prompt. Model output is not deterministic and run-to-run
  variance is not yet measured. Treat differences of a few points as noise.
- 183 cases; per-variant slices are 9–35 cases.

## Not yet built

Retrieval, appeal generation, judge calibration, and the red-team suite (stages 2–4).
