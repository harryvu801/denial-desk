# Denial Desk

> **Status: working MVP — rules lane, human review queue, audit log.** The model lane and
> the evaluation suites are next. **Synthetic data only. No PHI enters this system.**

Denial Desk reads Medicaid claim denials from X12 837P/835 files, works out what the payer
refused and why, and proposes the next action: corrected claim, appeal, write-off, or "a human
needs to decide." Every proposal goes to a review screen. Nothing is ever submitted to a
payer.

## Results so far

Measured on the default synthetic run (`make demo`: seed 42, 500 claims, 1,029 lines, 334
denied):

| | |
|---|---|
| Denials proposed by rules, **zero model spend** | **86%** (288 of 334) |
| Rules-lane proposals matching the generator's ground truth | 100% (288 of 288) |
| Denials routed to a human because no rule applies | 14% (46): medical necessity, bundling, units over authorization, coverage ended, unexplained CARC 16 |
| Model calls per claim / USD per claim | 0 / $0.00 — there is no model lane yet |
| Root-cause classification accuracy (model lane) | not built yet |
| Prompt-injection red-team pass rate | not built yet |

**Read the 86% with care.** It comes from a denial mix I declared in the generator, not
from real payer data. The generator never imports the rules, and the labels are root causes
rather than CARCs (CARC 16 alone covers three different causes), but a different mix would
give a different share. The 100% agreement is close to true by construction too: the rules
and the scenarios encode the same billing knowledge. Real denials are messier, so treat
every number here as an upper bound.

## What it looks like

`make demo` generates the data, ingests it and serves the review queue at
http://localhost:8000. The queue is sorted by dollars at risk. Each denial shows the CARC
and RARC definitions as of the adjudication date, the line as billed next to the line as
adjudicated, the proposed action with its citations and computed filing deadline, and three
buttons: approve, override, or reject. Every decision is appended to an audit log that the
database refuses to update or delete.

## Architecture

```
 837P files ─┐                         ┌─ playbook match ─▶ deterministic proposal ─┐
             ├─ parse ─▶ join on ──────┤                                            ├─▶ review queue ─▶ human decision
 835 files ──┘  (X12)   (PCN, REF*6R)  └─ no match ──────▶ needs_human ─────────────┘        │
                                                                                   append-only decision_audit
```

- **X12 parsing** (`ingest/x12/`) is hand-written and covers only the segments a denial
  needs. A CAS segment carries up to six reason/amount triplets. Each 835 line must balance
  (charge − paid = sum of adjustments), or parsing fails rather than producing wrong numbers.
- **The denial record** (`domain/`) keeps "as billed" (837) and "as adjudicated" (835) as
  separate types. A line counts as denied when it has an adjustment that is not patient
  responsibility and not CO-45 (fee-schedule reduction, which is on nearly every paid line).
- **The rules lane** (`triage/playbook.yaml`) has 13 entries keyed on CARC, plus RARC and a
  condition where one is needed. Each entry cites the code definition it relies on. Filing
  deadlines are computed in Python from public payer rules (`reference/payers.json`), and
  the screen flags payers whose limits are not yet verified.
- **Persistence** is SQLAlchemy over SQLite by default and Postgres via `DATABASE_URL`.
  Ingest is idempotent: an 835 is skipped by its TRN02 trace number, and each denial is
  unique on (patient control number, line control number).

Every decision, with what was rejected: [docs/DECISIONS.md](docs/DECISIONS.md). The full
internal guide: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Running it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make install   # uv sync --all-extras
make demo      # generate 500 synthetic claims, ingest them, serve http://localhost:8000
make test      # 24 unit tests, no network, no database server
```

## Scope and honesty

- **Synthetic data.** The four payers (UT, AZ, NV, ID) are modeled on public fee-for-service
  rules. The claims, members and providers are fabricated, and the denial mix is declared
  rather than measured.
- **Narrow X12.** The parsers read only the loops this system needs. Real clearinghouse files
  contain more, which is skipped. Reversals (CLP02 = 22) are reported and skipped; pairing a
  reversal with its re-adjudication is not built.
- **Citations.** Rules cite X12 code definitions and, for deadlines, the payer's public
  filing rule. Nevada's correction window and Idaho's manual section are not yet confirmed
  and are flagged as unverified on screen.
- **No model lane yet.** Anything the rules don't cover goes to a person. A model-assisted
  lane, judged against hand-labeled data, is the next stage.
- **Deliberately not built:** authentication, multi-tenancy, a polished frontend, real payer
  integration, auto-submission of anything (ADR-007, ADR-025).

## License

MIT
