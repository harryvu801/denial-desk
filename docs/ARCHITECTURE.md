# Denial Desk — internal architecture guide

The thorough version. The public README exists to make a stranger interested in ninety
seconds; this document exists so that the author can reconstruct the entire system from
memory, and so that a technical interviewer who goes three levels deep finds something there.

> Filled in as each stage completes. Current state: **rules lane + model lane (classification,
> replayed from recordings) + human lane + review screen + CI eval gate**. Sections for later
> stages are marked as not yet built.

---

## 1. What problem this solves

A home care agency bills the state Medicaid program for services such as personal care,
in 15-minute units. Some of those claim lines come back unpaid or underpaid. Each one is a
**denial**, and someone on the billing team has to work out *why* and *what to do*: fix
and resubmit the claim, appeal the decision, or accept the loss. The work is repetitive
(most denials are the same dozen reasons) and has deadlines (each state limits how long you
have to correct a claim). Getting it wrong either loses money that was owed or wastes time
chasing money that never will be paid.

The opportunity is that most denials are **mechanical**: the reason code plus a fact on the
claim fully determines the action. The rest need judgment. This system does the mechanical
part with rules, sends the judgment part to a person (later, to a model-assisted lane with
a person reviewing), and records every decision.

## 2. Domain primer

**837P** — the electronic professional claim the provider sends. Hierarchical: billing
provider (loop 2000A) → subscriber/member (2000B, with the payer in 2010BB) → claim (2300,
segment `CLM`) → service lines (2400, `LX` + `SV1` + `DTP*472` date of service + `REF*6R`
line control number).

**835** — the electronic remittance advice the payer sends back. Payment header (`BPR`,
payment date in BPR16; `TRN` trace number), payer (`N1*PR`), then per claim a `CLP` (CLP01
echoes the provider's claim number, CLP02 status, CLP07 the payer's own claim number, the
ICN), then per line an `SVC` with charge and paid amount, and `CAS` adjustments.

**CAS** — the "why we didn't pay it" segment. CAS01 is the **group code**: CO (contractual,
provider can't bill the patient), PR (patient responsibility), OA (other), PI (payer
initiated). Then up to six triplets of (reason code, amount, quantity). Rule that holds on
every valid line: **charge − paid = sum of CAS amounts.**

**CARC vs RARC** — CARC (Claim Adjustment Reason Code, in CAS) says *what* happened: 197 =
authorization absent. RARC (Remittance Advice Remark Code, in `LQ*HE` per line or `MOA` per
claim) adds detail: N290 = rendering provider ID missing. CARC 16 ("lacks information") is
nearly meaningless without its RARC. Both lists are maintained by X12 and change several
times a year, so a code is interpreted as of the adjudication date (ADR-004).

**CO-45** — "charge exceeds fee schedule". On almost every paid line, because providers bill
above the Medicaid rate. **Not a denial.** Forgetting this makes every line look denied.

**Timely filing** — each state limits how long after the date of service a claim can be
submitted (Utah 365 days, Arizona 6 months initial / 12 months to correct, Nevada 180 days,
Idaho 12 months; the federal floor is 12 months, 42 CFR 447.45). CARC 29 is the denial.

**Corrected claim vs appeal vs write-off** — a *corrected claim* fixes our own error and
resubmits (CLM05-3 frequency code 7). An *appeal* argues the payer was wrong. A *write-off*
accepts the loss. A *duplicate* (CARC 18) is none of these: the money lives on the original
claim, so the action is "no action, find the original".

**Worked example.** Line `PCN000116-2`, Arizona, S5125 attendant care, 96 units, $668.16
billed. The 835 says paid $0, `CAS*CO*198*668.16`, `LQ*HE*N362`: authorization exceeded,
units over the maximum. Is the authorization wrong, or were extra units actually delivered
and need a new authorization? That's judgment, so no rule matches and the line goes to the
human queue as `needs_human`. Compare `CAS*CO*197` with no `REF*G1` on the 837: the claim
plainly lacked the authorization number, so the rule proposes a corrected claim, with a
deadline computed from Arizona's 12-month correction window.

## 3. System overview

```
data/synthetic/*.837 ─┐
                      ├─▶ parse_837p / parse_835 ─▶ join ─▶ DenialRecord ─▶ triage ─▶ Resolution ─▶ store ─▶ review screen
data/synthetic/*.835 ─┘   (ingest/x12)             (ingest/join)            (triage/rules)          (persistence)  (api)
```

The path of one denial, with the shape at each hop:

1. **Raw text** → `tokenize()` → `list[Segment]` (tag + tuple of elements; 1-based `el(n)`
   so code reads like the implementation guide: `seg.el(7)` is CLP07).
2. **Segments** → `parse_837p()` → `list[SubmittedClaim]`, each with `SubmittedLine`s
   keyed by `line_control_number`. `parse_835()` → `Remittance` → `AdjudicatedClaim`s →
   `AdjudicatedLine`s with `Adjustment`s. Pydantic validation runs at construction: an 837
   whose line charges don't sum to CLM02, or an 835 line that doesn't balance, raises here.
3. **Join** on (patient control number, REF*6R) → `DenialRecord` for each line with at
   least one denial adjustment. It holds the submitted line, the adjudicated line, claim-level
   adjustments and remarks, the prior auth number, submission and adjudication dates.
   Derived: `denied_amount`, `primary_carc` (largest denial adjustment), `remark_codes`.
4. **Triage** → `Resolution` (lane, path, rule id, rationale, citations, filing deadline).
   The first matching playbook rule wins; no match → `Lane.HUMAN`, `NEEDS_HUMAN`.
5. **Store** → a `denials` row (the proposal, plus the full record as JSON) and a `proposed`
   row in `decision_audit`. Skipped if the key already exists.
6. **Review** → approve / override / reject updates `denials.status` and `final_path` and
   appends an audit row. Nothing leaves the system.

## 4. Component reference

### 4.1 `ingest/` — X12 parsing, joining and synthetic generation

- `x12/segments.py` — delimiters come from the ISA header, which is fixed-width: element
  separator at character 4, composite separator ISA16 at index 104, segment terminator at
  105. Tolerates newlines after terminators.
- `x12/parser_837p.py` — a single pass with a Python `match` statement over segment tags,
  using guards (`case "REF" if line is not None and seg.el(1) == "6R"`). Context (which claim,
  which line) is tracked by mutable builder dataclasses that build frozen Pydantic models at
  the end. Unknown segments are skipped.
- `x12/parser_835.py` — same shape. **CAS rules:** a CAS before the first SVC of a claim is
  claim-level; after an SVC it belongs to that line; one CAS explodes into up to six
  `Adjustment`s. `MOA03-07` are claim-level remark codes, `LQ*HE` line-level.
- `join.py` — emits only denied lines; reversals (CLP02=22) and unmatched lines become
  `JoinIssue`s rather than guesses.
- `pipeline.py` — directory → parse → skip seen TRN02 → join → triage → store.
- `generator.py` — see §5.1.

Edge cases deliberately not handled yet: reversal/re-adjudication pairs, replacement-claim
lineage, payers that don't echo REF*6R, PLB provider-level adjustments, 837 loops beyond
those listed.

### 4.2 `domain/` — the normalized denial record

Pure: no I/O. `models.py` (the records above), `codes.py` (a `CodeTable` that resolves a
code as of a date), `payers.py` (`FilingLimit` in days *or* calendar months, with month-end
clamping: six months after Aug 31 is Feb 28; `PayerRules`). Loading the JSON lives in
`reference/`, so `domain` stays pure.

Decisions: ADR-027 (what counts as a denial), ADR-028 (identity).

### 4.3 `triage/` — the deterministic lane

`playbook.yaml` holds 13 rules. A rule matches on `carc`, optional required `rarcs` (all
must be present), and an optional named `condition`. Conditions are Python functions in
`rules.py` (`submitted_after_initial_deadline`, `prior_auth_absent`, …), so the playbook stays
data while the logic stays typed and tested; an unknown condition name fails at load.

What is **not** in the playbook, by design: CARC 50 (medical necessity), 96, 97 (bundling),
198 (units over auth), 27 (coverage ended), bare CARC 16. Those are judgment and go to the
human lane.

**Time.** `triage(record, as_of=...)` takes the working date as a parameter instead of
calling `date.today()`, so the same record and date always give the same proposal. If a
corrected-claim deadline is already past on that date, the proposal becomes `needs_human`
(keeping the rule id) because late filing is a good-cause judgment. Ingest uses today in
production; synthetic data is *replayed*, each denial triaged as of its own 835 payment date.
The screen separately badges pending items whose deadline has passed since ingest.

Corrected-claim proposals get a deadline from the payer's correction window, counted from
the date of service. Appeals get one from the payer's appeal clocks (ADR-032): Nevada and
Utah count 30 days from the remittance, AHCCCS the later of 12 months from service or 60
days from the denial, and Idaho's window has not been read, so Idaho appeals carry no
deadline and the screen says so. `proposal_deadline` in `triage/rules.py` is the one
place this arithmetic lives, and both lanes use it.

### 4.4 `reference/` — committed facts

`carc.json`, `rarc.json` (only codes in use, shortened descriptions, with a source line),
`payers.json` (filing, correction and appeal limits, each citing the manual section it was
read from, with `verified` and `appeal_verified` flags). All four filing limits are
verified as of 2026-11-11; Idaho's appeal window is the one unverified entry, and the
review screen flags it. Sources and quotes: `docs/notes/2026-11-11-research.md`.

### 4.5 `persistence/` — schema

- `remittances` — unique `trace_number` (TRN02).
- `denials` — unique (`patient_control_number`, `line_control_number`); proposal columns
  are written once; `status` / `final_path` are the only mutable fields.
- `decision_audit` — append-only, enforced by **database triggers** created in an
  `after_create` hook: `RAISE(ABORT)` on SQLite, a plpgsql function on Postgres. An UPDATE or
  DELETE fails at the database, not by convention. Tested.

No Alembic migrations yet; `create_all` on startup. Add Alembic before the first schema
change that has to preserve data.

### 4.6 `api/` — review screen

FastAPI with Jinja templates, server-rendered (ADR-001). `create_app(database_url)` is a
factory (`uvicorn … --factory`) so tests get an isolated database and importing the module
opens nothing. One DB transaction per request via a dependency. Routes: `/` queue,
`/denials/{id}` detail + review form, `POST /denials/{id}/review`, `/audit`, `/healthz`.

The queue filters (status, lane, payer), searches (claim/line, procedure, CARC, RARC),
sorts on any column through a whitelist of column keys, and pages 50 rows at a time, all in
one query (`store.list_denials`). Stored values stay machine-friendly; templates show them
through one `label` filter ("deterministic" displays as "Rules"). Review rules are enforced
in `store.review`, not only in the page: an override or reject needs a note, approving a
`needs_human` item is refused, and a denial can be decided once (a second submission is a
409, so a double-click cannot append a conflicting decision to the audit log).

### 4.7 `agent/` — the model lane

Only for denials the rules hand to a human. `lane.py` runs it inside ingest: the proposer
(replay by default, so the demo needs no key) answers, `routing.apply_confidence_floor`
turns a low-confidence action into a handoff, a corrected-claim deadline is computed in
code, and the row stores the case file and the model's metadata (model, prompt, confidence,
evidence paths, recorded cost). The audit actor is `model:<id>`. A handoff keeps the
model's rationale for the reviewer. The lane takes the same `as_of` the rules use: a
corrected claim whose correction window has already closed on that date becomes a handoff
with the deadline kept, exactly as the rules lane does. The demo uses the eval set's seed
and size so every human-lane denial has a recording, and `dd demo` always replays, whatever
`MODEL_LANE` says.

- `schemas.py` — `ModelProposal` (action, root cause, confidence, evidence paths, rationale)
  and `strict_json_schema()`, which turns it into a structured-outputs schema: `$ref`s
  inlined, every property required, unsupported keywords stripped (Pydantic re-checks them).
- `prompts/classify/v1/` — `system.md` (the author's, not yet written; a placeholder the
  live proposer refuses to send) and `user.md` (`<denial>` JSON, `<case_file>` JSON,
  `<untrusted source="care_note">`). Each loaded prompt carries a hash of its text.
- `input.py` — builds the request. Angle brackets in untrusted text are escaped so a care
  note cannot close or forge a delimiter.
- `proposer.py` — the `Proposer` protocol: live, recording, replay, stub (ADR-030). Live:
  one retry on invalid output with the error fed back; refusal, truncation or a second
  failure → `needs_human`.

### 4.8 Not yet built

Stubs with a docstring and `TODO(stage-N)`: `retrieval/` (chunkers, index, hybrid
retriever: stage 2), `agent/tools.py` and `agent/loop.py` (the tool-calling agent and
appeal drafts: stage 3), `routing/confidence.py:route` (dollar-aware review depth: stage
3), `security/` (sanitize, budgets, redaction: stage 4), `obs/` (tracing, cost
attribution: stage 5), and the robustness and safety suites under `evals/`. See CLAUDE.md
for the stage plan.

## 5. The evaluation system

### 5.1 Ground truth from the generator

`generate(out_dir, n_claims, seed)` writes 837/835 files grouped one per (payer, date),
because BHT04 and BPR16 are file-level dates, plus `labels.jsonl` (one row per line:
denied?, root cause, CARC, RARCs) and `manifest.json` (seed, generator version, declared
distribution). Fully deterministic: one `random.Random(seed)` instance, a fixed start date,
sorted output.

Fourteen scenarios with declared weights (missing prior auth 18, timely filing 14, duplicate
12, …). The evidence is planted in the 837 where possible, so a classifier has to read the
claim and not just the CARC.

**Case files (generator 0.2.0, ADR-029).** Each denied line also gets a case file in
`case_files.jsonl`: authorizations, eligibility spans, EVV visits, and a care note with one
or two distractor sentences. Labels gain `expected_action`, `variant` and an unscored
`suggestion`. The human-lane causes each have two variants that hinge on one fact:

| Cause | Variant → expected action |
|---|---|
| Units over auth (198) | extension on file → corrected claim · no extension → write-off |
| Coverage ended (27) | retroactive reinstatement → needs human (suggest rebill) · no coverage → write-off |
| Medical necessity (50) | need documented → appeal · not supported → write-off |
| Bundled (97) | distinct visits → appeal · overlapping visits → write-off |
| Bare CARC 16 | member ID changed → corrected claim · unexplained → needs human |

At 2,000 claims (seed 42): 183 human-lane cases across the ten variants.

### 5.2 Model-lane accuracy suite

`python -m evals.suites.accuracy [--proposer replay|stub|live] [--record]`. The eval set is
the human-lane output of the real pipeline on seed 42 / 2,000 claims (183 cases). Three
systems are scored on it: the model; `carc_majority`, the most common expected action per
CARC fit on seed 7 (the "does reading the case file help" bar — **47.0%**); and
`always_abstain` (25.1%, because 46 of 183 cases should go to a human). Model failures count
as `needs_human`. Reported: accuracy, abstention precision/recall, accuracy by variant,
root cause and payer, failures, cost per claim, p50/p95 latency. The run record (git SHA,
prompt hash, model, effort, dataset seeds, settings minus secrets) goes to `evals/results/`.

### 5.3 What is measured today

- Round-trip: generate → parse → join reproduces exactly the labeled denied lines, with
  matching CARCs (unit test).
- Rules lane vs ground truth: every scenario maps to the expected (lane, path) (unit test);
  1,086 of 1,269 denials (86%) take the rules lane on the default run.
- Model lane: the accuracy suite (§5.2), replayed. Error types per ADR-031, the confidence
  floor sweep, slices by variant, root cause and payer, recorded cost and latency. A fifth,
  reported-only count: needless handoffs whose rationale named the expected action, found
  by a lexical match (an upper bound; a judge or human label would replace it).

- Run-to-run variance (`evals/suites/robustness.py`): a seeded 50-case sample, five runs
  per model, replayed from `data/recordings/variance/`. Sonnet: stdev 0.9 points, 49 of 50
  unanimous, no wrong action in any run. Haiku: stdev 3.0, 18 of 50 flip, 23 wrong in at
  least one run.

The rest of the robustness suite (prompt sensitivity, degraded retrieval, the adversarial
set) and the safety suite are not built; asking the runner for them is an error.

### 5.4 The CI gate

`python -m evals.runner --suites accuracy --gate` (`make eval-gate`) runs the accuracy
suite on the committed recordings, flattens the run record into named metrics and compares
them with `evals/baseline.json`. The rules are in `evals/runner.py` (`GATES`): a *floor in
points* for accuracy and the rules-lane share, a *ceiling in percent* for cost per claim,
and an *absolute ceiling of zero* for wrong actions and for failures. The baseline holds
only numbers and tolerances, so editing it can move a limit but never remove a check. Any
metric without a tolerance is recorded for diffing and not gated.

It runs on every push and PR with no key and no database, because replay is free
(ADR-030). A prompt or input change without a re-recording surfaces as `missing_recording`
failures, which fail the gate directly and again through the accuracy drop. The fix is to
re-record deliberately and then bless the run with `--write-baseline` in its own commit
(ADR-019). Metric extraction and tolerance arithmetic are unit-tested.

## 6. Security

Current controls: no auto-submission path exists (architectural); the audit log is
append-only at the database (architectural); synthetic data only; the model lane sees only
denials the rules could not settle, and every proposal is reviewed (architectural).

The injection surface exists now: the care note in each case file is third-party free text
read by the model. Controls on it are all **probabilistic**: angle brackets are escaped so
the note cannot close or forge a delimiter, it is wrapped in `<untrusted source="care_note">`,
and the system prompt says delimited content is data, never instruction (ADR-020). None of
this is measured yet; the model lane has no tools, so a successful injection could change
an action but could not reach anything else. Threat model and the red-team suite: stage 4.

## 7. Operations

`make demo` (generate + ingest + serve on :8000), `make test`, `make lint`, `make typecheck`.
SQLite at `data/denial_desk.db` (gitignored); delete it to reset. Postgres via
`DATABASE_URL` and `make db-up` (needs Docker).

## 8. What I would do differently

<!-- Real entries only, written as they happen. -->

- *Surprise worth keeping:* the scaffold's original idempotency key — "claim control number
  + line number" — doesn't exist as such in an 835. Lines are echoed by REF*6R, not by LX,
  and "claim control number" can mean either CLP01 or CLP07. ADR-028.
- *Surprise worth keeping:* labeling synthetic denials by CARC would have made
  classification a field lookup. Labels are root causes now (ADR-027).

- *Surprise worth keeping:* the first version proposed corrected claims whose deadlines
  had already passed — nothing compared the deadline to a date. The first fix (one global
  "working date" after the last remittance) was also wrong: the latest outlier set the date
  for everyone. The right model is per-event: triage as of when the 835 arrived.

- *Surprise worth keeping:* SQLAlchemy's `JSON` column stores Python `None` as JSON `null`,
  not SQL `NULL`, so `IS NOT NULL` matched every row. `JSON(none_as_null=True)`. A test on
  the model lane caught it.
- *Surprise worth keeping:* scaling the demo to 2,000 claims surfaced one rules-lane
  "disagreement" with ground truth. The rule was right: timely filing is per line, and the
  generator had judged a multi-line claim late from its first line's date of service.

## 9. Open questions

- Which real-world source, if any, can calibrate the denial-mix weights?
- Idaho's claim-appeal window: in the "General Information and Requirements for
  Providers" handbook, not yet read. Until then Idaho appeals carry no deadline.
- How should reversal + re-adjudication pairs update an existing denial without breaking the
  audit history?
