# Evaluation report

> Regenerated from the latest gated run. This file is a deliverable — link it directly in
> job applications, because it is more persuasive than the repository.

**Run:** `<git sha>` · **Date:** `<date>` · **Resolution model:** `<model>` · **Judge:** `<model>`
**Datasets:** retrieval `<v>` · classification `<v>` · generation `<v>` · adversarial `<v>`

## Headline

| Metric | Value | Baseline | Δ |
|---|---|---|---|
| Deterministic share (no model spend) | | | |
| Root-cause accuracy | | | |
| Worst slice | | | |
| Retrieval recall@5 | | | |
| Grounding (judge) | | | |
| Hallucination rate (adversarial) | | | |
| Indirect-injection pass rate | | | |
| USD per claim | | | |

## Axis 1 — accuracy

### Retrieval
<!-- recall@5, nDCG@10, and the chunking comparison table. State which strategy won and why
     you think it won. -->

### Classification
<!-- Accuracy, per-class F1, confusion matrix. Then the slices: by payer, by denial category,
     by procedure type. Name the worst slice explicitly. -->

### Generation
<!-- Per-rubric-dimension scores. -->

## Axis 2 — robustness
<!-- Run-to-run variance, prompt sensitivity, degraded-retrieval behavior, adversarial set. -->

## Axis 3 — cost and latency
<!-- USD/claim, tokens split retrieval vs generation, p50/p95, deterministic share. -->

## Axis 4 — safety
<!-- Pass rate per attack class, with the cases that failed and what was changed. -->

## Judge calibration

| Rubric dimension | Cohen's κ | Gated? |
|---|---|---|
| Grounding | | |
| Correct CARC addressed | | |
| No fabrication | | |
| Deadline correct | | |

<!-- Then the most important paragraph in this document: what the judge and the human
     disagreed about, and what that revealed. This is the source of the writeup. -->

## Failure analysis

<!-- Be specific and be honest. Categories of failure, worked examples of each, and what you
     would fix next. An eval report with no failures is an eval report nobody believes. -->
