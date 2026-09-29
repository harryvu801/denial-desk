# Kickoff prompt

Paste the block below into Claude Code in VS Code, with `~/code/denial-desk` open as the
workspace. It is written for the first session; the follow-up prompts at the end cover later
stages.

---

```text
This repository is a scaffold. Read CLAUDE.md, docs/DECISIONS.md, and README.md before you
write anything — the ADRs are the contract for this codebase and I want you working inside
them, not around them.

Context on me: I'm a senior full-stack engineer with 8 years in TypeScript and Angular,
deep domain knowledge in Medicaid billing, and limited Python. I'm building this to learn AI
application engineering and to be interviewed on it. So the way we work matters as much as
what gets built:

- Explain the approach and the tradeoffs before you write a non-trivial module, and wait for
  me to respond.
- When Python idiom differs from how I'd do it in TypeScript, point it out in a sentence.
- Don't write more than one component ahead of my understanding.
- When we hit something I'll be asked about in an interview — the chunking comparison, the
  judge calibration, the injection cases — tell me, and let me write it with you reviewing.
- Any decision worth an ADR is mine to make. Give me options and a recommendation, not a
  fait accompli.

I want to start with stage 1: the spine and the deterministic lane. Specifically:

1. The synthetic 837P/835 generator (src/denial_desk/ingest/generator.py). Deterministic from
   a seed, four state payers, a skewed denial-reason distribution, and a ground-truth manifest
   recording why each denial was created. That manifest becomes my labeled classification set,
   so its shape matters — see ADR-005 and ADR-013.
2. The X12 parsers (ingest/x12/). Narrow scope per ADR-003: only the loops needed to
   reconstruct a denial. I want to write the 835 CAS handling myself — that's the part I know
   best and the part I'll be asked about.
3. The normalized denial record (domain/models.py), finished and validated.
4. The rules lane (triage/) with 12–20 real playbook entries, each carrying a policy citation.
5. A minimal FastAPI surface and the Postgres schema, with the idempotency key from ADR-016
   and the append-only audit table from ADR-007.
6. One naive LLM classification call as a baseline for stage 2 to beat.

Before you start, do three things:

First, tell me anything in the scaffold you think is wrong. I'd rather fix an architectural
mistake now than in week six. Be blunt — if an ADR is poorly reasoned, say which one and why.

Second, propose the order you'd build stage 1 in, and where you think I'll get stuck.

Third, set up the Python toolchain and confirm it runs: uv sync, ruff, mypy --strict, pytest.
I want a green baseline before we add anything.

Two documentation requirements that run throughout, not at the end:

**README.md** is the public GitHub-facing document. Its job is to make a stranger — a hiring
manager with ninety seconds — understand what this is and why it's unusual. It leads with
measured results, not a feature list: the share of denials resolved with zero model spend,
classification accuracy including the worst slice stated honestly, the red-team pass rate,
and cost per claim. Architecture in a diagram and a few paragraphs. A scope-and-honesty
section that admits what's synthetic, what's narrow, and what's deliberately not built. Short.
No marketing voice.

**docs/ARCHITECTURE.md** is for me. It's the document I'd reread the night before an
interview, and it should let me reconstruct the whole system from memory: a domain primer
someone with no healthcare background could follow, the path of a single denial through every
component with the data shape at each hop, a per-package reference, the evaluation system in
full, the security model with each control marked architectural or probabilistic, operations,
and an honest "what I'd do differently."

Update both as we go, at the end of each stage. Don't leave them to week eight — a doc
written at the end is a summary, and I want the parts that surprised me recorded while
they're still surprising.
```

---

## Follow-up prompts

**Stage 2 — retrieval and golden sets**

```text
Stage 1 is done and green. Moving to stage 2 per CLAUDE.md: corpus ingestion, the three
chunking strategies from ADR-008, hybrid retrieval with reranking (ADR-009), and the refusal
floor (ADR-011).

Build the chunkers and the retrieval pipeline with me. I'll hand-label the golden sets myself
— help me design the labeling schema and build the tooling, but the labels are mine, and I
want them done before the system is good (ADR-013).

Deliverable for this stage is the first real eval report: retrieval numbers, the chunking
comparison with a written explanation of why the winner won, and classification accuracy
against the week-2 baseline. Then update the baseline in its own commit.
```

**Stage 3 — agent, judge, calibration**

```text
Stage 3: the tool-calling agent (ADR-010, ADR-021), appeal generation, the judge, and
calibration.

I'm hand-grading 150 appeal letters before we build the judge — that order is not negotiable
per ADR-014, and I don't want to see any judge output until my labels are done. Build me the
grading tool first.

Once my labels exist, we build the judge and report Cohen's kappa per rubric dimension. Then
we read the disagreements together — that's the part I actually care about.
```

**Stage 4 — threat model and red team**

```text
Stage 4: security. Threat model first, in docs/THREAT_MODEL.md, before a single attack case —
the cases exist to test hypotheses about this system, not to be a generic checklist.

I want to write the indirect-injection cases myself; that's the interview story. Help me with
the harness, the tool-abuse and denial-of-wallet cases, and reviewing what I write.

For every control, be explicit about whether it's architectural or probabilistic. Then wire
promptfoo's OWASP suite in as a floor underneath my cases, and add the safety suite to the CI
gate with zero tolerance per ADR-019.
```

**Stage 5 — eval infrastructure and ship**

```text
Stage 5: turn the eval scripts into a system per ADR-017 — versioned datasets, run records
carrying git SHA and every version, diffable results, one command that reproduces a historical
run. Then online sampling with drift detection, Terraform, tracing, and the CI gate finished.

Then the writing: both READMEs finished with real numbers, the eval report, the failure
analysis, and the "what I'd do differently" section. Help me outline a blog post about what
the judge calibration or the injection testing actually revealed — the specific surprising
finding, not a tutorial.
```

## Notes on using these

- Run `/init` in Claude Code first if it offers to; it will read `CLAUDE.md` and keep it in
  context across the session.
- When Claude starts writing code you don't follow, stop it. The fastest way to lose the value
  of this project is to end up with a working system you can't explain.
- Keep a running note of things you had to look up. That list is the honest answer to "what
  did you learn," and it's a better interview answer than a feature tour.
