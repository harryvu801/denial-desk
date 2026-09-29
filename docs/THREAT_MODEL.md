# Threat model

> Write this **before** writing red-team cases. The cases exist to test hypotheses about how
> this specific system can be attacked; writing them first produces a generic checklist
> instead.

## Scope

What is in scope, what is out, and the deployment assumption being modeled (a billing team's
internal tool, operated by trained reviewers, ingesting public policy documents and payer
remittances).

## Assets

<!-- What an attacker would want: claim data, the ability to cause an incorrect submission to
     a state payer, model spend, reviewer trust. Rank them. -->

## Trust boundaries

The central one, and the reason this document exists:

> Third-party-authored text — state Medicaid policy PDFs and 835 remark free text — is read
> verbatim into the same context window that decides which tools to call and what the appeal
> letter says. From the model's position, a crafted string inside a policy document is
> indistinguishable from the system's own instructions.

<!-- Enumerate the rest: file ingestion, the corpus download, the review UI, the database. -->

## Attacker goals

<!-- Per asset. Be concrete: "cause an appeal letter to contain another patient's data",
     "cause a write-off recommendation on an appealable denial", "exhaust the token budget". -->

## Attack classes

### 1. Indirect prompt injection via the policy corpus
### 2. Tool-call abuse
### 3. Data leakage
### 4. Denial of wallet

<!-- For each: mechanism, realistic variants, which control addresses it, whether that
     control is ARCHITECTURAL (holds deterministically) or PROBABILISTIC (a mitigation that
     degrades under pressure), and how it is tested. Being explicit about that distinction is
     the most valuable thing in this document. -->

## Controls

| Control | Attack class | Type | ADR | Tested by |
|---|---|---|---|---|
| Delimited, provenance-tagged untrusted content | 1 | probabilistic | ADR-020 | |
| Server-side tool argument scoping | 2 | architectural | ADR-021 | |
| Citation resolution check | 1, 3 | architectural | ADR-012 | |
| Output identifier scan | 3 | architectural | ADR-022 | |
| Step / token / dollar budgets | 4 | architectural | ADR-018 | |
| Retrieval refusal floor | 1 | probabilistic | ADR-011 | |
| Human review of everything | all | architectural | ADR-007 | |

## Residual risk

<!-- What remains undefended, and what would be needed to close it. A threat model with no
     residual risk section is not finished. -->
