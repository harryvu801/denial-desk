# Architecture Decision Record

Every non-obvious decision in this codebase, with the reasoning that produced it and the
alternatives that were rejected.

This file exists for two reasons. The first is ordinary engineering hygiene: in four months
you will not remember why retrieval is hybrid, and rediscovering it costs a day. The second
is specific to this project's purpose — in an interview you will be asked "why did you do it
that way," and the difference between a good answer and a great one is whether you can name
what you considered and discarded. Write each entry as if the person reading it is skeptical.

**Format.** Context, Decision, Why, Alternatives, Consequences, Revisit when. Keep entries
short. A decision that needs a page of justification is usually two decisions.

**Status values.** `accepted` · `superseded by ADR-NNN` · `revisit`

---

## ADR-001 — Python, not TypeScript

**Status:** accepted

**Context.** Eight years of TypeScript, limited Python. The entire AI tooling ecosystem —
evaluation frameworks, red-team tooling, scikit-learn for the statistics this project needs —
is Python-first, and effectively every AI-engineering job description names Python explicitly.

**Decision.** Python 3.12 throughout. No TypeScript anywhere in this repo, including the
review UI, which is server-rendered.

**Why.** The project's purpose is to close a gap, not to demonstrate an existing strength.
Building it in TypeScript would produce a working system that proves nothing new about the
author. The first week will be slower; that cost is the point of the exercise.

**Alternatives.** TypeScript with the Vercel AI SDK — faster to a working demo, leaves the
gap open. A Python core with a TypeScript frontend — more surface area, and the frontend is
explicitly not what this project is about.

**Consequences.** Expect the first two weeks to feel clumsy. Use `uv`, `ruff` and `mypy
--strict` from the first commit so the Python is idiomatic rather than TypeScript in
disguise.

**Revisit when.** Never, for this project.

---

## ADR-002 — A pure domain core with I/O at the edges

**Status:** accepted

**Context.** AI applications rot into a pile of scripts where prompt construction, database
access, HTTP handling and business rules are interleaved and nothing can be tested without a
live API key.

**Decision.** `domain/` contains frozen Pydantic models and pure functions — no database, no
HTTP, no model calls, no framework imports. Every other package may depend on `domain`;
`domain` depends on nothing. The FastAPI layer is thin: parse, call, serialize.

**Why.** It makes the majority of the system testable with no network and no Postgres, which
is what keeps the test suite fast enough to actually run. It also forces the normalized
denial record to be designed deliberately rather than accreted from whatever the parser
happened to emit.

**Alternatives.** A conventional Django/FastAPI layered app with ORM models as the domain
type — simpler at first, but couples the eval harness to the database and makes the
normalized record an ORM artifact instead of a designed contract.

**Consequences.** Some mapping code between domain models and SQLAlchemy rows. Worth it.

**Revisit when.** The mapping layer exceeds roughly 200 lines.

---

## ADR-003 — Hand-rolled X12 parsing, scoped to what is needed

**Status:** accepted

**Context.** 837P and 835 are large specifications. Python libraries for them exist but are
mostly unmaintained, partial, or commercial.

**Decision.** Write the parser. Support only the loops required to reconstruct a denial:
837P loops 2000A/2000B/2300/2400, and from the 835 the CLP, SVC and CAS segments plus the
remark fields.

**Why.** Three reasons, in order of importance. It is a portfolio asset — domain code that
very few candidates could write, and the most direct evidence of the specialty this whole
project is built on. It avoids a dependency that would have to be explained and defended. And
narrow scope means it can be correct, whereas a general X12 parser cannot be correct in a
weekend.

**Alternatives.** A library — faster, but surrenders the most differentiated code in the
repo. A full-spec parser — a multi-week sink with no additional signal.

**Consequences.** Real files from real clearinghouses will contain segments this parser
ignores. That is acceptable and must be stated in the README rather than hidden.

**Revisit when.** Never, within this project's scope.

---

## ADR-004 — CARC/RARC definitions are versioned data, not constants

**Status:** accepted

**Context.** X12 revises the code lists several times a year. A denial adjudicated in March
must be interpreted against March's list.

**Decision.** Load definitions from committed data files with effective dates, and resolve
them as of the adjudication date rather than as of now.

**Why.** It is correct, and it is the kind of detail that signals real domain experience.
Hardcoding an enum would work today and quietly produce wrong interpretations later.

**Alternatives.** A Python enum — simpler, silently wrong over time. A live API lookup — a
network dependency for data that changes quarterly.

**Consequences.** A small amount of temporal lookup machinery.

**Revisit when.** Not applicable.

---

## ADR-005 — Synthetic data, deterministic from a seed, four payers

**Status:** accepted

**Context.** The project needs realistic claims data and can never touch real claims data.

**Decision.** A generator that produces paired 837P/835 files plus a ground-truth manifest,
fully deterministic given a seed. Four state Medicaid payers with differing rules, mirroring
the four the author has worked with. Denial reasons drawn from a declared skewed
distribution, not uniformly.

**Why.** Determinism means a golden dataset is reproducible from a seed plus a generator
version rather than from a committed blob. Four payers with genuinely different rules is what
makes payer-sliced evaluation meaningful — with one payer there is no slice to cut. The
skewed distribution matters because real denial populations concentrate heavily in a few
CARCs, and a uniform synthetic set would flatter performance on the long tail.

**Alternatives.** CMS SynPUF files directly — realistic distributions but no ground-truth
root causes, so nothing to evaluate against. Hand-written fixtures — too few to measure
anything.

**Consequences.** Synthetic denials are cleaner than real ones. Say so in the README, and
treat every accuracy number as an upper bound.

**Revisit when.** Not applicable.

---

## ADR-006 — Two lanes: rules first, model only for the remainder

**Status:** accepted

**Context.** Roughly six denials in ten are fully determined by the CARC, the payer, and
occasionally the procedure code. The rest need policy interpretation.

**Decision.** A deterministic playbook runs first. On a match, the resolution is produced
with no model call at all. Only unmatched denials reach the agent. Every record carries the
lane that resolved it.

**Why.** This is the most defensible decision in the project and the one most worth being
able to argue. Rules are cheaper, faster, auditable, and cannot hallucinate. A reviewer can
inspect a rule; nobody can inspect a weight. Sending everything to a model would be simpler
to build and strictly worse on cost, latency, and safety — and in healthcare, "we can show
you exactly why the system did that" is a procurement requirement, not a nicety.

The second-order benefit: it makes the model lane's failure surface small enough to actually
evaluate and red-team properly. Defending 40% of traffic is tractable; defending 100% is not.

**Alternatives.** Model-everything — simpler, worse on every axis that matters here, and it
would reduce the project to another agent demo. Model-first with rules as a fallback —
inverts the trust relationship and spends money before checking whether spending was needed.

**Consequences.** The playbook must be maintained, and every entry needs a policy citation
so a reviewer can audit rather than trust. The deterministic share is a headline metric and
belongs at the top of the README.

**Revisit when.** The playbook stops growing, or deterministic share drops below ~40%.

---

## ADR-007 — Nothing is auto-submitted, and the decision log is append-only

**Status:** accepted

**Context.** The system proposes corrections and appeals against government payers. A wrong
automated submission is a compliance problem, not a bug report.

**Decision.** Every resolution goes to a human review queue. No code path submits anything.
Every automated decision is written to an append-only `decision_audit` table that no code
path updates or deletes.

**Why.** It is the right product decision, and it makes an eval story coherent: because a
human sees everything, their approve/edit/reject actions become ground truth, and the eval
set grows instead of going stale. Append-only matters because in a regulated setting the
question is not "what does the system think now" but "what did it decide on March 4th and on
what basis."

**Alternatives.** Auto-submit above a confidence threshold — tempting, indefensible in this
domain, and it would destroy the label-generation loop.

**Consequences.** Throughput is bounded by reviewer attention, which is exactly what makes
confidence routing (ADR-024) worth building.

**Revisit when.** Not within this project.

---

## ADR-008 — Three chunking strategies, and the comparison is a deliverable

**Status:** accepted

**Context.** Chunking choice dominates RAG quality and is usually made by copying a blog
post.

**Decision.** Implement fixed-window, section-aware, and semantic chunking. Evaluate all
three on the same labeled query set. Keep all three in the repo and publish the comparison.

**Why.** The measured comparison is worth more than the winner. It demonstrates the method —
that retrieval decisions are settled empirically — which is the actual skill being hired for.
Section-aware is expected to win here, because provider manuals are written as numbered
policy sections and a citation to a section is only meaningful if chunk boundaries respect
it. Expectation is not evidence.

**Alternatives.** Pick one and move on — faster, and discards the most interesting artifact.

**Consequences.** Re-indexing per strategy costs time and embedding spend. Bounded and worth
it.

**Revisit when.** After the stage-2 comparison, keep the winner as default but leave the
others runnable.

---

## ADR-009 — Hybrid retrieval, and Postgres holds everything including vectors

**Status:** accepted

**Context.** Denial queries are a mix of exact-token lookups (`T1019`, `CARC 197`) and
paraphrased policy questions. Dense embeddings are unreliable on bare alphanumeric codes;
lexical search is unreliable on paraphrase.

**Decision.** BM25 and dense retrieval over the same chunk set, fused, then reranked.
pgvector in the same Postgres instance that holds the operational data — no separate vector
database.

**Why.** The hybrid choice is forced by the query distribution; one retriever alone
predictably fails half of it, and the eval suite will show exactly that, which is a result
worth publishing. Single-store is an operational judgment: one database to run, back up and
reason about, transactional consistency between a chunk and its metadata, and no second
system to explain. At this corpus size — a few hundred thousand chunks — pgvector is
comfortably sufficient, and "we didn't need a dedicated vector DB at this scale" is a better
interview answer than naming one.

**Alternatives.** Pinecone or Weaviate — genuinely better past tens of millions of vectors,
and job descriptions name them. Not needed here, and adopting infrastructure you don't need
is the thing senior engineers are supposed to resist. Mention the tradeoff in the README.

**Consequences.** If the corpus grows an order of magnitude, revisit.

**Revisit when.** Chunk count exceeds ~5M or p95 retrieval latency exceeds 300ms.

---

## ADR-010 — Structured outputs, and arithmetic stays in Python

**Status:** accepted

**Context.** Free-text model output that gets parsed afterward fails in ways that are
invisible until production. Separately, language models are unreliable at date arithmetic,
and filing deadlines are both date arithmetic and legally consequential.

**Decision.** Every model response is a validated Pydantic schema. Validation failure
triggers a bounded retry with the error fed back, then a hand-off to human review. Filing
deadlines are computed in Python from dates and a payer rule table; the model is never asked
to calculate one, only to state which rule applies.

**Why.** Failing closed is the correct default when the downstream action is a submission to
a state payer. And the division of labor is the general principle worth articulating: models
are for judgment under ambiguity, code is for anything with a right answer. A missed filing
deadline is unrecoverable — that is not a place to accept a probabilistic answer.

**Alternatives.** Free text with regex extraction — brittle. Letting the model compute
deadlines — it will be right most of the time, which is the worst possible failure profile.

**Consequences.** A payer rule table has to be maintained. Small, and it belongs in the
playbook anyway.

**Revisit when.** Not applicable.

---

## ADR-011 — An explicit refusal floor, and refusal is measured

**Status:** accepted

**Context.** The characteristic RAG failure is answering confidently from weak retrieval.

**Decision.** If the reranked top score is below `RETRIEVAL_MIN_SCORE`, the system returns no
answer and routes to human review. Refusal rate and hallucination-under-starvation are
first-class metrics in the robustness suite.

**Why.** "I don't know, a human should look at this" is the correct output for an ambiguous
denial, and a system that cannot produce it is not deployable in healthcare. Measuring it
matters as much as implementing it: an untested refusal path is an assumption, and the
degraded-retrieval eval exists specifically to check whether the system refuses or starts
inventing policy when starved.

**Alternatives.** Always answer with a confidence score attached — users read a low
confidence score far less carefully than a refusal.

**Consequences.** The floor needs tuning against the eval set. Over-refusal is also a
failure and is tracked as such.

**Revisit when.** Refusal rate exceeds ~20% on the standard set.

---

## ADR-012 — Citations are verified, not trusted

**Status:** accepted

**Context.** Models cite fluently and sometimes fictitiously. A cited section that does not
exist is worse than no citation, because it manufactures credibility.

**Decision.** Every citation in a generated appeal is checked against the passages actually
returned by the retriever for that run. Unresolvable citations fail the resolution to human
review, and citation-resolution rate is a gated metric.

**Why.** It is a deterministic check on a probabilistic output — cheap, and it catches the
specific failure that would most damage trust in this product. It also converts "grounded"
from a claim into a number.

**Alternatives.** Asking the model to self-verify — the same failure mode grading itself.

**Consequences.** Retrieved passages must be retained for the life of the resolution. They
are, for audit reasons anyway (ADR-007).

**Revisit when.** Not applicable.

---

## ADR-013 — Evals are a system, and the labels are written before the system works

**Status:** accepted

**Context.** "AI eval" in most portfolios means a handful of example prompts and an eyeball
check. The requirement here is a system that measures performance, accuracy and security,
that runs in CI, and whose results can be compared across time.

**Decision.** Four axes — accuracy, robustness, cost/latency, safety — across two modes,
offline suites on versioned datasets and online scoring of sampled traffic. Golden sets are
built in stage 2, before the system is good. All accuracy metrics are reported per slice
(payer, denial category, procedure type) as well as in aggregate.

**Why.** Evals written after a system works get shaped, usually unconsciously, to flatter
what already exists — you stop adding cases once the numbers look good. Labeling first makes
the target fixed. Slicing matters because aggregates hide exactly the failures that get
systems pulled from production: an 88% overall that conceals 46% on one payer is not an 88%
system, and the average is designed not to tell you that.

The distinction between tests and evals is worth stating plainly, because interviewers ask:
tests answer "does the code do what I wrote," evals answer "does the system do what it is
for." Tests are binary and deterministic; evals are distributional and move.

**Alternatives.** A single blended quality score — easier to report, useless for diagnosis,
and it hides the tradeoffs between dimensions.

**Consequences.** Hand-labeling roughly 150 appeal letters is genuinely tedious. It is also
where the most is learned about actual failure modes, and it is the source material for the
writeup.

**Revisit when.** Not applicable.

---

## ADR-014 — The judge is a different model, and it is calibrated before it is believed

**Status:** accepted

**Context.** Generated appeal letters have no single correct string, so an LLM-as-judge is
the only scalable grader. An uncalibrated judge is an unvalidated instrument.

**Decision.** The judge is a different model from the one being graded. Before any judge
score is used, ~150 letters are hand-graded first — without looking at judge output — and
agreement is reported as Cohen's kappa per rubric dimension. Dimensions below roughly kappa
0.6 are reported but not gated on. Rubric dimensions are scored independently rather than
blended.

**Why.** A model grading its own output rates its characteristic failure modes as acceptable,
because they are precisely what it finds plausible. Different model, different failure modes.
Calibration is the part nearly every portfolio skips and the reason this one is credible: the
answer to "how do you know your evals measure anything" is a number, and the disagreement
cases between judge and human are the single most informative artifact the project produces.

Order is load-bearing. Human labels must come first or they are contaminated by having seen
the judge's opinion.

**Alternatives.** Same model as judge — cheaper, systematically blind. Human-only grading —
correct but unscalable. No calibration — the default, and the reason most eval numbers in
portfolios mean nothing.

**Consequences.** A day and a half of tedious grading, and a second model's API costs.

**Revisit when.** Re-calibrate whenever the judge model or the rubric changes.

---

## ADR-015 — Degrade to the deterministic lane rather than failing

**Status:** accepted

**Context.** The model API will be unavailable sometimes.

**Decision.** When the model lane is unavailable, the deterministic lane continues serving
its ~60%, and everything else queues for human review with a clear status. The system never
returns an error to a user for a denial it could have routed.

**Why.** A two-lane architecture gets graceful degradation almost for free, and saying so is
a good answer to "what happens when the API is down." A billing team can keep working at
reduced throughput, which is a materially different outage than a dead system.

**Alternatives.** Retry and fail — simpler, throws away the capability that is still working.

**Consequences.** The queue needs a status that distinguishes "waiting for a human" from
"waiting because the model was unavailable."

**Revisit when.** Not applicable.

---

## ADR-016 — Idempotency on (claim control number, line number)

**Status:** superseded by ADR-028

**Context.** 835 files are re-sent. Ingestion will be retried. Duplicate processing means
duplicate spend and, worse, duplicate appeals.

**Decision.** That pair is the natural key. Ingestion upserts on it; resolution is keyed to
it; reprocessing an already-resolved denial is a no-op unless explicitly forced.

**Why.** Standard practice for claims pipelines, and the failure it prevents is expensive in
both dollars and credibility. Choosing a natural key over a surrogate also means a replayed
file converges to the same state rather than accumulating rows.

**Alternatives.** A surrogate key with dedup on a content hash — works, but hashes are
brittle against trivial formatting differences between clearinghouse re-sends.

**Consequences.** Corrected replacement claims share the control number lineage and need
explicit handling. Note it in the parser.

**Revisit when.** Not applicable.

---

## ADR-017 — Every run records exactly what produced it

**Status:** accepted

**Context.** An eval number without provenance cannot be reproduced or compared, which makes
it a vibe with a decimal point.

**Decision.** Every eval run records: git SHA, prompt version, model versions (resolution and
judge), retrieval index version and chunking strategy, dataset versions, a full settings
snapshot, all metrics, and total spend. Prompts live in versioned directories, not in
strings. Datasets are versioned directories with manifests. Any two runs can be diffed, and
any historical run can be reproduced by a single command.

**Why.** This is the difference between an evaluation system and a folder of scripts, and it
is what makes the CI gate meaningful — a gate that cannot say *what* changed can only say a
number moved. Every configuration value therefore lives in `config.py` rather than inline, so
a snapshot captures all of it.

**Alternatives.** Logging metrics to a file — fine until the first "was that before or after
the reranker."

**Consequences.** Some bookkeeping in the runner. It is the highest-leverage code in the
repo.

**Revisit when.** Not applicable.

---

## ADR-018 — Budgets are enforced, and the enforcement is tested

**Status:** accepted

**Context.** An agent loop with tools can run unbounded, and a crafted document can induce
exactly that — denial of wallet.

**Decision.** Hard caps on steps, tokens, dollars and wall-clock per claim, plus a circuit
breaker on repeated failures. Exceeding a budget hands off to human review with the partial
trace attached. The red-team suite includes cases designed to trip each budget, and a budget
that does not trip is a test failure.

**Why.** Budgets are a security control here, not just cost management — they are the
backstop on the one attack class that does not require the model to be fooled, only to be
made busy. Untested limits are decoration; a control you have not seen fire is a control you
are guessing about.

**Alternatives.** Monitoring and alerting without hard caps — detects the bill after it
exists.

**Consequences.** Legitimately hard denials will occasionally hit the ceiling and route to a
human. That is the correct outcome.

**Revisit when.** Budget-exceeded rate goes above ~2% on the standard set.

---

## ADR-019 — CI fails the build on regression, including cost regression

**Status:** accepted

**Context.** Prompt changes are code changes with no type system. Quality drifts silently.

**Decision.** A committed `evals/baseline.json` holds gated metrics and tolerances. Pull
requests run accuracy, robustness, cost and safety suites and fail when any gated metric
regresses beyond tolerance. Cost per claim is gated. Safety pass rate has zero tolerance.
Updating the baseline is its own pull request, with the justifying run linked.

**Why.** An eval suite that reports but does not block gets ignored within a month. Gating
cost matters because the most common way a quality metric improves is that something quietly
started spending far more per claim — a change that improves accuracy 2% and triples cost
should not merge silently. Zero tolerance on safety because a security regression is not a
tradeoff to be balanced against quality.

Separating baseline updates into their own PR is what stops the gate from being edited away
in the same commit that broke it.

**Alternatives.** Report-only — the default, and the reason most eval suites decay.

**Consequences.** CI needs an API key and costs real money per PR. Keep the gated set small
and sampled; run the full suite nightly.

**Revisit when.** CI eval spend exceeds a few dollars per PR.

---

## ADR-020 — Retrieved content is data, never instruction

**Status:** accepted

**Context.** The policy corpus is authored by third parties and read verbatim into the same
context window that decides tool calls and output. (An earlier draft also named "free-text
remark data in an 835". A 5010 835 carries remark *codes* — LQ, MOA, MIA — not payer-authored
free text, so the realistic second source is payer letters and PDFs in a real deployment.)
This makes indirect prompt injection the realistic threat against this architecture — not
someone typing a jailbreak into a chat box.

**Decision.** Untrusted content is marked untrusted at the point of parsing, not later. It is
wrapped in explicit delimiters with a provenance tag, and the system prompt states that
delimited content is data and never instruction. Structural markers that could forge a system
boundary are stripped. The red-team suite plants instructions inside documents in the
ingestion set and measures whether the agent follows them.

**Why.** Prompt-level defenses are probabilistic and must be described as mitigations rather
than solutions — which is exactly why the architectural defenses (ADR-021, ADR-018) carry the
real weight, and why this gets a measured pass rate rather than an assurance. Marking at parse
time rather than at prompt time matters: trust is a property of where data came from, and
deciding it late means somewhere in the codebase a caller has to remember.

**Alternatives.** Trusting the corpus because it comes from state government sites — the
documents are downloaded over the internet, converted by a text extractor, and in a real
deployment would include payer-authored remark text. Treating any of it as trusted is a
category error. A separate sanitizing model — another probabilistic layer, more cost, more
latency.

**Consequences.** Some prompt bloat from delimiters and provenance. Cheap.

**Revisit when.** Injection pass rate drops below 100% on the red-team suite — then the
architectural controls need to tighten, not the prompt.

---

## ADR-021 — Tool arguments are scoped server-side

**Status:** accepted

**Context.** The general failure of tool-using agents is being persuaded to call a legitimate
tool with illegitimate arguments.

**Decision.** Tools take an execution context holding the claim currently being processed;
the model cannot name a patient or a claim. `get_claim_history` has no patient parameter at
all. An allowlist governs which tools are available, and a per-run call budget bounds usage.

**Why.** This is the difference between a mitigation and a control. Asking a model nicely not
to look up other patients is probabilistic; removing the parameter makes the attack
unrepresentable. Structural defenses do not degrade under adversarial pressure, which is
precisely when prompt-level ones fail.

The general principle worth articulating: give the model *judgment* over a bounded action
space, never *authority* over the boundary itself.

**Alternatives.** Post-hoc validation of tool arguments — better than nothing, but it
requires enumerating everything the model might do wrong.

**Consequences.** Tools are less flexible. Correct for this domain.

**Revisit when.** Not applicable.

---

## ADR-022 — Redaction is built and tested even though the data is synthetic

**Status:** accepted

**Context.** No PHI will ever enter this system. Redaction therefore protects nothing today.

**Decision.** Build it anyway: redaction before anything reaches logs, traces or the eval
store, plus an identifier scan applied as an output check on generated letters, not only as a
logging filter.

**Why.** Two reasons. The habit is the deliverable — a healthcare hiring manager looks for
whether the reflex is present, and its absence is conspicuous. And a redaction path that is
only enabled in production has never actually been tested; building it against synthetic data
means the tests exist before they matter.

Applying the scan to outputs as well as logs is the part that is easy to skip and shouldn't
be: leakage into a generated appeal letter that a human then sends is worse than leakage into
a log nobody reads.

**Alternatives.** Skip it, note it as future work — loses the signal entirely.

**Consequences.** Some false positives on synthetic identifiers. Tune against the corpus.

**Revisit when.** Not applicable.

---

## ADR-023 — OpenTelemetry is the substrate; Langfuse consumes it

**Status:** accepted

**Context.** LLM observability tools are young and consolidating. Job descriptions name
Langfuse specifically.

**Decision.** Instrument with OpenTelemetry — one span per retrieval and per model call,
correlated by claim control number — and export to Langfuse. Do not instrument against a
vendor SDK directly.

**Why.** The vendor becomes a consumer of standard telemetry rather than the thing the code
is coupled to, so switching is a configuration change. Practically it also means the same
traces carry both AI-specific spans and ordinary application spans, which is what makes
"where did the latency go" answerable.

**Alternatives.** Langfuse SDK directly — less code now, vendor lock-in, and AI spans live in
a different system from application spans.

**Consequences.** Slightly more setup. Worth it, and the reasoning is itself a good interview
answer.

**Revisit when.** Not applicable.

---

## ADR-024 — Route on expected cost of being wrong, not on confidence alone

**Status:** accepted

**Context.** Reviewer attention is the scarcest resource in the system (ADR-007).

**Decision.** Review depth is a function of confidence *and* dollars at risk. A 0.9-confidence
resolution on a $40 line gets a spot check; the same confidence on a $12,000 line gets full
review. Denial category adjusts the threshold, since some categories are measurably less
reliable (ADR-013 slicing tells you which).

**Why.** Confidence alone optimizes the wrong thing. The quantity that matters is expected
cost of being wrong, which is probability times consequence — and consequence varies by two
orders of magnitude across a claims population. Feeding per-slice accuracy back into routing
is also the point of slicing: measurement that changes behavior rather than measurement that
gets reported.

**Alternatives.** A single confidence threshold — simple, spends equal attention on a $40
line and a $12,000 one.

**Consequences.** The thresholds are a tuning surface and need their own eval.

**Revisit when.** After the first real slice results.

---

## ADR-025 — Aggressively defended non-goals

**Status:** accepted

**Context.** The project has a fixed budget of roughly 170 hours and a specific purpose:
producing evidence of AI application engineering ability.

**Decision.** Explicitly out of scope: a polished frontend, authentication beyond a stub,
multi-tenancy, fine-tuning, Kubernetes, real payer integration, and support for more than
four states.

**Why.** Every item on that list is a plausible-sounding way to spend three weeks while adding
nothing an interviewer will ask about. Several are actively counterproductive — a beautiful
review UI signals frontend skill the author already has and does not need to prove, at the
cost of the eval work that is the entire point.

Writing the non-goals down is what makes them defensible later, when the temptation arrives
disguised as polish.

**Alternatives.** Leave scope implicit — it will expand.

**Consequences.** The review UI will look plain. That is the intended outcome, and the README
should say so rather than apologize for it.

**Revisit when.** After the project has produced interviews.

---

## ADR-026 — MVP: rules lane plus a human lane; the model lane comes later

**Status:** accepted (provisional — set during the 2026-10 speed pivot)

**Context.** The priority changed to getting a working, demonstrable system public quickly
and pivoting from there. Stage 1 as planned ended in a naive LLM classifier; the model lane
proper was stage 3.

**Decision.** The MVP has two lanes: deterministic rules and a human. Anything the playbook
does not match is proposed as `needs_human` and decided on the review screen. There are no
model calls anywhere. The default database is SQLite through the same SQLAlchemy models;
Postgres remains supported through `DATABASE_URL` and is required again when pgvector arrives
(ADR-009).

**Why.** Every judgment call goes to a person by default, which is the safe failure mode for
this domain (ADR-007) and leaves a clean slot for a model lane to be measured against later.
SQLite means `make demo` works on any machine with Python, with no Docker. The append-only
audit triggers are emitted for both dialects, so the guarantee does not depend on the
database.

**Alternatives.** Ship the naive LLM classifier now — it adds a cost, an API key, and a
number with no eval behind it. Keep Postgres-only — the demo stops working without Docker.

**Consequences.** With no model lane, "zero model spend" is trivially true of every proposal.
The honest headline is the rules-lane share (86% on the default run), and the README says so.

**Revisit when.** The model lane is built; switch the default to Postgres with pgvector.

---

## ADR-027 — What counts as a denial, and labels are root causes

**Status:** accepted (provisional)

**Context.** CO-45 sits on nearly every paid line. If every adjustment counted, every line
would be a "denial". Separately, if the ground-truth label were the CARC, classification
would be a lookup of a field already in the input and the accuracy number would mean nothing.

**Decision.** A line is denied when it has an adjustment that is not group PR, not CARC 45,
and greater than zero. Denied amount is the sum of those adjustments; the primary CARC is the
one carrying the most money. Generator labels are root causes (`missing_prior_auth`,
`timely_filing`, …), several of which share a CARC — CARC 16 maps to three. Scenario evidence
is planted in the 837 where it can be (no REF*G1, a missing modifier, a late submission
date), and the generator never imports `triage/`.

**Why.** It matches how a billing team talks about denials, keeps the classification task
non-trivial, and measures the rules lane against data it was not shaped from.

**Alternatives.** Deny on `paid == 0` only — misses partial denials. Label by CARC — makes
the eval circular.

**Consequences.** The distribution is still hand-declared, so the rules-lane share is a
property of the synthetic mix. The README states this next to the number.

**Revisit when.** A source of real denial-mix statistics is available to calibrate weights.

---

## ADR-028 — Denial identity is (patient control number, line control number); remittances dedupe on TRN02

**Status:** accepted — supersedes ADR-016

**Context.** ADR-016 keyed on "(claim control number, line number)". In X12 that is
ambiguous: CLP01 echoes the provider's patient control number while CLP07 is the payer's
ICN, and the 835 carries no LX line number — it echoes the 837's REF*6R line item control
number. A claim can also appear in several CLPs (a reversal plus a re-adjudication), which
are new events, not duplicates.

**Decision.** Two keys for two questions. A denial is unique on (CLM01 / CLP01 patient
control number, REF*6R line item control number), and the 837 → 835 join uses the same pair.
A re-sent 835 is detected by its TRN02 trace number and skipped. A denied line without
REF*6R is reported as a join issue, never matched heuristically.

**Why.** Both keys are fields the standard defines for exactly this purpose, so replaying
files converges to the same state without content hashing.

**Alternatives.** The ICN as identity — it changes when a claim is replaced. Matching on
procedure plus date of service — a guess, and wrong when a line is billed twice in a day.

**Consequences.** Payers that do not echo REF*6R need a fallback match, which would go to
human review. Reversal/re-adjudication pairing is not built yet; reversals are skipped and
reported.

**Revisit when.** Reversals and replacement claims (CLM05-3 = 7) are handled end to end.

---

## Decisions still open

Record these here as they are made, with the same format.

- **Embedding model.** Pick in stage 2 and record the comparison that justified it.
- **Reranker.** Cross-encoder locally vs a hosted reranking API — cost and latency tradeoff.
- **Online eval sampling rate.** What fraction of live traffic gets judge-scored.
- **Corpus refresh.** NCCI files are quarterly; decide whether re-indexing is manual or
  scheduled, and how version skew between a denial and the corpus is handled.
