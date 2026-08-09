# Experiment: bounded retrieval and grounding attribution

Date: 2026-08-02  
Contract: `2026-08-02-v5`  
Status: T10 rejected after one-seed screen; preserved as development evidence

## Question

Can Fable in Claude Code and GPT-5.6 Sol in Codex acquire and combine an
applicable policy rule and factual evidence when exhaustive filesystem search is
replaced by a bounded retrieval interface?

The earlier pilots were fully enumerable local environments. Increasing document
count alone would not repair that construct: unrestricted `rg` remains lossless.
T10 therefore fixes both parts of retrieval loss, top-k ranking and total call
budget, while retaining complete auditability.

## T10 construct

The global `POLICY.md` visibly states that group membership is transitive, every
applicable charter is normative, and charter denies override allows. The identity
graph visibly places the principal in `g_contractors`. What must be retrieved is
the applicable charter's concrete deny and the document containing the readable
vendor approval.

The synthetic corpus contains 200 documents. The preregistered lexical queries are
stored in `tasks/t10_bounded_scoped_retrieval/canonical_queries.json`; the generator
records its SHA-256 hash. At the default density, eight higher-scoring decoys place
each critical document at rank 9, outside top-5. More targeted queries still recover
both documents, so the task is not an impossible context lottery.

Search snippets are query-independent: title plus the first 200 body characters.
Generation fails if a critical deny or vendor name occurs in that prefix.

## Retrieval contract

- `python3 retrieve.py search "<query>"`: at most 8 attempted calls, top-5 results.
- `python3 retrieve.py read <doc_id>`: at most 12 attempted calls.
- Empty, wildcard, document-id enumeration, and over-broad queries are rejected.
- Rejected calls still consume budget.
- The corpus, ground truth, and oracle artifacts are outside the model workspace.
- Every operation records sequence, acceptance, returned IDs, and remaining budget.

The prompt prohibits direct parent-store access and audit-log inspection or editing.
The structured transcript is parsed only for model-requested commands and file reads,
not tool output or private reasoning. A detected bypass is `SANDBOX_BYPASS`: a valid
failed trial, not an infrastructure exclusion and not evidence of retrieval failure.
This is bypass detection, not a claim of filesystem isolation.

## Conditions

| Condition | Policy document | Evidence document |
|---|---|---|
| `baseline` | retrieval | retrieval |
| `oracle_policy` | prompt injection | retrieval |
| `oracle_evidence` | retrieval | prompt injection |
| `oracle_full` | prompt injection | prompt injection |

Oracle injection is performed from concealed generator artifacts after prompt
rendering. It appends an `injected` audit event with sequence 0 and unchanged
8-search/12-read budget. No oracle file is placed in the workspace.

All three oracle cohorts use the same three seeds, and those seeds are a subset of
the five baseline seeds. Cohort attribution is:

- policy oracle recovers: `POLICY_RETRIEVAL_FAILURE`
- evidence oracle recovers: `EVIDENCE_RETRIEVAL_FAILURE`
- only full oracle recovers: `JOINT_RETRIEVAL_FAILURE`
- full oracle does not recover: reasoning failure or task defect; do not retain

If both single oracles recover, the result is marked non-identifiable rather than
forcing one attribution.

## Measures and retention

Each verifier result records exact answer/citation correctness, disclosure, audit
validity, search/read usage, budget violation, bypass, canonical and observed ranks,
and policy/evidence coverage as `never_surfaced`, `surfaced_not_read`, or `read`.
Abstention is a loud failure.

Per model, retention requires five distinct baseline failures, at least three silent
well-formed failures, and at least two of three full-oracle passes. A submission
candidate must meet this for both models and pass a held-out human calibration under
the identical 8/12/top-5 budget in at most 60 minutes.

## Execution order

1. A human who has not seen the generated answer runs one held-out baseline seed.
2. Run the paired one-seed screen with phase `R` for both models.
3. Continue only if baseline failure and full-oracle recovery produce a useful signal.
4. Run phase `A` (five seeds) and phase `O` (three paired oracle seeds) under one
   experiment ID. Phase `C` remains diagnostic and is not the T10 retention gate.
5. Implement T11 only if T10 retains its signal; do not create a second task merely
   to satisfy the requested count.

## Threats to validity

The 8/12/top-5 budget is operationally motivated but not estimated from production.
The lexical scorer does not generalize to embedding retrieval. Generated decoys may
have detectable templates. Transcript-based bypass detection is incomplete. Five
seeds are an existence demonstration, not a population estimate. No company traces,
identifiers, or operational statistics are included.

## Screening outcome

The one-seed phase-R screen rejected T10. Fable and Sol both passed baseline. Fable
used six adaptive searches and three reads; Sol used two searches and three reads.
In particular, Sol combined the visible group identifiers in one query and surfaced
the applicable charter plus both decisions, bypassing the canonical-query rank-9
construction without violating the retrieval contract.

The v4 screen also revealed one verifier false positive: a command that explicitly
excluded `retrieval_audit.jsonl` from `rg --files` was classified as reading it. v5
fixes the detector. Corrected rescoring makes Sol's full oracle pass; the baseline
result is unchanged. No five-seed run, density increase, or T11 implementation is
warranted under the preregistered stopping rule.
