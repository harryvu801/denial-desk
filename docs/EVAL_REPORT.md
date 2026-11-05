# Evaluation report

> Built from committed recordings. Reproduce every number below with no API key:
> `uv run python -m evals.suites.accuracy --model claude-sonnet-5-5` (or `claude-haiku-4-5`).

**Date:** 2026-11-05 · **Prompt:** `classify/v1@8fdffd5b9cd9` (drafted by Claude, approved
unedited) · **Generator:** 0.4.0, seed 42, 2,000 claims · **Baseline fit:** seed 7

## Headline

| | Sonnet 5.5 | Haiku 4.5 | CARC lookup | Always abstain |
|---|---|---|---|---|
| Action accuracy | 44.3% | **50.8%** | 47.0% | 25.1% |
| **Wrong actions** (asserted, and wrong) | **0** | 31 | 44 | 0 |
| Missed handoffs (asserted where a person should decide) | 33 | 39 | 0 | 0 |
| Needless handoffs (abstained when evidence settled it) | 69 | 20 | 53 | 137 |
| USD per claim | $0.0063 | $0.0026 | $0 | $0 |
| Latency p50 / p95 | 2.2 s / 2.8 s | 2.9 s / 4.7 s | — | — |

183 cases: the denials the rules lane hands to a human (14% of denied lines), each with a
synthetic case file. Pipeline-wide, 86% of denials get a rules proposal with zero model
spend.

**Accuracy ranks these models backwards.** Haiku wins on accuracy by asserting more, and 31
of its assertions are wrong — 26 of them appeals against denials the case file supports
(for example, appealing a medical-necessity denial whose care note says the member is
independent). It also asserted an action on 6 of the 13 cases with no explaining evidence at
all. Sonnet never asserted a wrong action: its misses are 69 needless handoffs and 33 missed
handoffs, every one of the latter on retroactive reinstatement.

In this domain a wrong appeal or write-off costs money and credibility, and a needless
handoff costs a reviewer a minute. The metric to drive to zero is wrong actions; the one to
drive down next is needless handoffs.

**Neither model clears the CARC lookup on accuracy by much, and the lookup makes 44 wrong
actions.** Reading the case file is what keeps Sonnet's wrong-action count at zero.

## Worst slices (Sonnet 5.5)

| Variant | Expected | Sonnet | Why |
|---|---|---|---|
| retro_reinstated | needs_human | 0/33 — appealed 32 | The author's policy (suggest a rebill, assert nothing) is not in the prompt. Prompt v2. |
| no_extension | write_off | 0/18 — handed off | Correct reasoning, then deferred ("retro-auth and appeal, or write off"). |
| overlapping_visits | write_off | 0/10 — handed off | Same pattern. |
| distinct_visits | appeal | 0/15 — handed off | Same pattern; often named the right action in its rationale. |
| need_not_supported | write_off | 0/9 — handed off | Same pattern. |

By payer, Sonnet ranges from 34.7% (NV) to 55.1% (ID). The payer spread follows the mix of
variants per payer, not payer rules: the model lane does not use payer-specific policy yet.

## Run history

| Run | What changed | Sonnet acc. | Finding |
|---|---|---|---|
| 1 | first live run, generator 0.2.0 | 33.3% | Eval defects, not model defects: member ID missing from the input; visits clamped at midnight no longer matched billed units (the model caught it); replay keys ignored input data. [Details](../evals/history/2026-11-05-run1-sonnet-v1-gen0.2.0/README.md) |
| 2 | fixes above; paid services added for bundling (0.4.0) | 44.3% | Over-abstention traced to the prompt's "when unsure, choose needs_human"; retro-reinstatement policy missing from the prompt. |

Total spend for both runs, both models: about $2.80.

## Honest limits

- The case files and the prompt are written by the same people, so this measures whether a
  model reads the evidence, not whether it copes with a real case file (ADR-029).
- One run per model. Model output is not deterministic and run-to-run variance is not yet
  measured. Treat differences of a few points as noise.
- 183 cases; per-variant slices are 9–35 cases.

## Not yet built

Retrieval, appeal generation, judge calibration, and the red-team suite (stages 2–4).
