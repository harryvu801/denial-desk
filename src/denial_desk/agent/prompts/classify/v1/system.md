TODO(author): write this prompt

<!--
Notes for the author — delete this whole comment block when you write the prompt; the
loader refuses to send it to a paid model while the marker line above is present.

What the model receives, in the user message (see user.md):
  <denial>     JSON: payer, procedure, modifiers, units, charge, dates (service,
               submission, adjudication), prior auth on the claim, CARC and RARCs with
               their definitions as of the adjudication date, adjustments, denied amount.
  <case_file>  JSON: authorizations[], eligibility[], visits[] (EVV).
  <untrusted source="care_note">  third-party free text. Data, never instruction (ADR-020).

What it must return (enforced by structured outputs, see agent/schemas.py ModelProposal):
  action       corrected_claim | appeal | write_off | no_action | needs_human
  root_cause   one of the RootCause values, or unknown
  confidence   0..1
  evidence     paths into the input it relied on, e.g. "authorizations[1]", "care_note"
  rationale    at most two sentences

Things the prompt has to get across — your words, your judgment:
  - These denials are the ones the deterministic rules could not settle.
  - The decision rests on the case file, not the CARC alone.
  - When the evidence does not settle the action, needs_human is the correct answer,
    not a failure. Suggesting a next step in the rationale is fine; asserting one is not.
  - Never compute a filing deadline; deadlines are computed in code (ADR-010).
  - The care note may contain text that looks like instructions. It is data.

Write this before you have seen any model output (ADR-013).
-->
