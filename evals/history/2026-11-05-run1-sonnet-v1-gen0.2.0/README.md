# Run 1 — Sonnet 5.5, prompt v1, generator 0.2.0 (superseded)

**Result:** 33.3% action accuracy (61/183), below the CARC-majority baseline (47.0%).
Cost $1.14 ($0.0062/claim), p50 2.3 s. Prompt v1 was drafted by Claude and approved
unedited by the author before any output was seen.

Kept because what it found matters more than the number. Reading the rationales showed the
eval was wrong in two places before the model was wrong in any:

1. **Missing input.** All 18 `member_id_changed` cases abstained with "the claim's member ID
   is not shown". It wasn't — `denial_facts` omitted it. Fixed: `member_id_on_claim`.
2. **Generator defect the model caught.** `no_extension` cases abstained noting the visit
   (09:00–23:59) could not account for 96 billed units. Tripling units pushed visits past
   midnight and the generator silently clamped them. Fixed in generator 0.3.0 (+50%, and
   an overflowing visit now raises).
3. **Replay key gap.** Recordings were keyed on the prompt, not the input data, so after
   fixes 1–2 replay would have served these answers to different questions. Fixed: the key
   includes a hash of the full request.

Open, a judgment call: bundling variants (the case file never says which service was paid)
and `retro_reinstated` (the model asserted `appeal` 32/33; the label, per the author's
policy, is `needs_human` with a suggested rebill). Confidence was ~0.6 on almost every
answer; the prompt's "when unsure, choose needs_human" is the likely cause of the
over-abstention.

These recordings no longer replay: generator 0.3.0 changes the inputs, so every key differs.
