# Denial Desk — internal architecture guide

The thorough version. The public README exists to make a stranger interested in ninety
seconds; this document exists so that the author can reconstruct the entire system from
memory, and so that a technical interviewer who goes three levels deep finds something there.

> Filled in as each stage completes. Current state: **MVP (rules lane + human lane + review
> screen)**, per ADR-026. Sections for later stages are marked as not yet built.

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

Corrected-claim proposals get a deadline from the payer's correction window. Appeals don't
get one yet: appeal windows weren't researched for the MVP, so the screen shows "—" rather
than guessing.

### 4.4 `reference/` — committed facts

`carc.json`, `rarc.json` (only codes in use, shortened descriptions, with a source line),
`payers.json` (filing limits with citations and a `verified` flag). Unverified payers (NV's
correction window, ID's manual section) are flagged on the review screen.

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
opens nothing. One DB transaction per request via a dependency. Routes: `/` queue (filter by
status, lane, payer; sorted by dollars at risk), `/denials/{id}` detail + review form,
`POST /denials/{id}/review`, `/audit`, `/healthz`.

### 4.7 Not yet built

`retrieval/`, `agent/`, `routing/`, `review/` (beyond the screen), `security/`, `obs/`, and
`evals/` are stubs. See CLAUDE.md for the stage plan.

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

### 5.2 What is measured today

- Round-trip: generate → parse → join reproduces exactly the labeled denied lines, with
  matching CARCs (unit test).
- Rules lane vs ground truth: every scenario maps to the expected (lane, path) (unit test);
  288 of 334 denials (86%) take the rules lane on the default run.

Classification accuracy, robustness, cost and safety suites are not built. The CI eval job
references a runner that is still a stub.

## 6. Security

Current controls: no auto-submission path exists (architectural); the audit log is
append-only at the database (architectural); synthetic data only. The injection surface
does not exist yet because no model reads untrusted text. Threat model: stage 4.

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

## 9. Open questions

- Which real-world source, if any, can calibrate the denial-mix weights?
- Appeal windows per payer: not yet researched, so appeals carry no deadline.
- How should reversal + re-adjudication pairs update an existing denial without breaking the
  audit history?
