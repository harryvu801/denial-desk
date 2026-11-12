# Denial Desk

> **Status: working end to end — rules lane, model lane (replayed, no API key needed),
> human review queue, append-only audit log.** **Synthetic data only. No PHI enters this system.**

Denial Desk reads Medicaid claim denials from X12 837P/835 files, works out what the payer
refused and why, and proposes the next action: corrected claim, appeal, write-off, or "a human
needs to decide." Every proposal goes to a review screen. Nothing is ever submitted to a
payer.

## Results so far

**Rules lane** — the demo run (`make demo`: seed 42, 2,000 claims, 1,269 denied lines):

| | |
|---|---|
| Denials proposed by rules, **zero model spend** | **86%** (1,086 of 1,269) |
| Rules-lane proposals matching the generator's ground truth | 100% (1,086 of 1,086) |
| Left for judgment → model lane | 14% (183): 77 get a model proposal, 106 go to a person |

**Model lane** — the denials the rules leave behind (183 cases from 2,000 claims), each with
a case file of authorizations, eligibility, visit records and a care note.
[Full report](docs/EVAL_REPORT.md).

| | Sonnet 5.5 | Haiku 4.5 | CARC lookup baseline |
|---|---|---|---|
| Action accuracy | **67.2%** | 57.9% | 47.0% |
| **Wrong actions asserted** | **0** | 35 | 44 |
| Missed handoffs (asserted where a person must decide) | **0** | 23 | 0 |
| USD per claim | $0.0063 | $0.0026 | $0 |

Prompt v2, 183 cases. Sonnet never asserted a wrong action; its 60 misses are handoffs to a
reviewer who would resolve them quickly (52 of the 60 name the expected action in their
rationale). Haiku is cheaper and scores higher than the lookup,
but 35 of its assertions are wrong — mostly appeals against denials its own evidence
supports. In this domain a wrong appeal costs far more than a handoff, so the comparison
that matters is the wrong-action row, not accuracy.

The same prompt change that lifted Sonnet from 44.3% to 67.2% made Haiku *more* wrong (31 →
35 wrong actions): prompt improvements do not transfer between models for free. Moving the
confidence threshold out of the prompt and into code (re-scored from recordings at no cost)
showed that for Sonnet no threshold helps — at 0.9 it degrades to the always-abstain
baseline. [Full report](docs/EVAL_REPORT.md).

**Run-to-run variance** (the same 50 cases, five runs each, replayed from recordings):

| | Sonnet 5.5 | Haiku 4.5 |
|---|---|---|
| Accuracy, mean (min to max) | 74.4% (74 to 76) | 59.6% (56 to 64) |
| Cases that changed their answer across runs | 1 of 50 | 18 of 50 |
| Cases wrong in at least one run | **0** | 23 |

Sonnet's answer is stable, so differences of a few points between its runs are noise and
larger ones are not. Haiku's is not: a single Haiku run overstates or understates it by up
to four points, and more than a third of its cases flip between runs.

The first live run scored 33%, below the baseline. Reading the model's rationales found two
bugs in the eval, not the model — a missing input field, and synthetic visit records that no
longer matched billed units, which the model noticed and the tests had not.
[Run 1 write-up](evals/history/2026-11-05-run1-sonnet-v1-gen0.2.0/README.md).

**Read every number with care.** The denial mix, the case files and the prompt are written
by the same people, so the rules-lane share is a property of the declared mix and the model
numbers measure whether a model reads the evidence, not whether it copes with real data.
Treat them as upper bounds. Prompt-injection red-teaming is not built yet.

Every model number above reproduces with no API key: responses are recorded once and
replayed (`make eval-accuracy`). CI replays the same recordings on every push and fails
the build if accuracy drops more than 2 points, cost per claim rises more than 15%, or a
single wrong action or missing recording appears (`make eval-gate`, baseline in
`evals/baseline.json`, updated only in its own commit).

## What it looks like

`make demo` generates the data, ingests it — rules first, then the model for what the rules
leave, replayed from committed recordings — and serves the review queue at
http://localhost:8000. The queue is sorted by dollars at risk and filterable by lane. Each
denial shows the CARC and RARC definitions as of the adjudication date, the line as billed
next to the line as adjudicated, and the proposal: a cited rule, or the model's action,
confidence and the case-file items it relied on (outlined in the case file below it, with
the care note marked as untrusted third-party text). Filing deadlines are always computed
in code. A reviewer approves, overrides or rejects; every decision is appended to an audit
log the database refuses to update or delete.

![Review queue filtered to the model lane: action, code tooltips, computed deadlines, an expired-window flag](docs/screenshots/review-queue-model-lane.png)

![A model proposal: the model's rationale and confidence, the case-file items it cited outlined, the care note marked untrusted, and the review controls](docs/screenshots/detail-model-proposal.png)

## Architecture

```
 837P files ─┐                         ┌─ playbook match ─▶ deterministic proposal ──────────────┐
             ├─ parse ─▶ join on ──────┤                                                         ├─▶ review queue ─▶ human decision
 835 files ──┘  (X12)   (PCN, REF*6R)  └─ no match ─▶ model lane (case file) ─▶ action or needs_human ┘        │
                                                      replayed from recordings                      append-only decision_audit
```

- **X12 parsing** (`ingest/x12/`) is hand-written and covers only the segments a denial
  needs. A CAS segment carries up to six reason/amount triplets. Each 835 line must balance
  (charge − paid = sum of adjustments), or parsing fails rather than producing wrong numbers.
- **The denial record** (`domain/`) keeps "as billed" (837) and "as adjudicated" (835) as
  separate types. A line counts as denied when it has an adjustment that is not patient
  responsibility and not CO-45 (fee-schedule reduction, which is on nearly every paid line).
- **The rules lane** (`triage/playbook.yaml`) has 13 entries keyed on CARC, plus RARC and a
  condition where one is needed. Each entry cites the code definition it relies on. Filing
  and appeal deadlines are computed in Python from public payer rules
  (`reference/payers.json`, each limit citing the manual section it was read from); where
  a window is unknown the screen says so instead of showing a number.
- **Persistence** is SQLAlchemy over SQLite by default and Postgres via `DATABASE_URL`.
  Ingest is idempotent: an 835 is skipped by its TRN02 trace number, and each denial is
  unique on (patient control number, line control number).

Every decision, with what was rejected: [docs/DECISIONS.md](docs/DECISIONS.md). The full
internal guide: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Running it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make install        # uv sync --all-extras
make demo           # generate 2,000 synthetic claims, ingest them, serve http://localhost:8000
make test           # 54 unit tests, no network, no database server
make eval-accuracy  # model-lane eval, replayed from committed recordings (no API key)
make eval-gate      # what CI runs: the same replay, gated against evals/baseline.json
make eval-variance  # run-to-run variance, five recorded runs on 50 cases (no API key)
```

## Scope and honesty

- **Synthetic data.** The four payers (UT, AZ, NV, ID) are modeled on public fee-for-service
  rules. The claims, members and providers are fabricated, and the denial mix is declared
  rather than measured.
- **Narrow X12.** The parsers read only the loops this system needs. Real clearinghouse files
  contain more, which is skipped. Reversals (CLP02 = 22) are reported and skipped; pairing a
  reversal with its re-adjudication is not built.
- **Citations.** Rules cite X12 code definitions and, for deadlines, the payer manual
  section the limit was read from. Idaho's claim-appeal window has not been read yet, so
  Idaho appeals carry no deadline and the screen says so. AHCCCS's eligibility-posting
  clock is not modeled.
- **Model lane limits.** It classifies the next action from a case file; it does not
  retrieve policy, draft appeals, or call tools yet (stages 2 and 3). A proposal whose
  filing or appeal window has already closed is handed to a person, as the rules lane does.
- **Deliberately not built:** authentication, multi-tenancy, a polished frontend, real payer
  integration, auto-submission of anything (ADR-007, ADR-025).

## License

MIT
