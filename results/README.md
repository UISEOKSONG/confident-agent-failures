# Public result summary

This directory contains aggregate results suitable for the public repository. Raw
`runs/` transcripts are intentionally not committed because CLI streams contain
machine-local paths, session identifiers, and other runtime metadata. They remain
available locally and can be regenerated from the recorded seeds.

## Phase A and C results

Pass counts are model passes, so lower baseline values indicate more frequent failure.
Each row reports one task-model pair against the **per-model A/C gate** defined in
`SPEC.md` section 9.0. Clearing that gate is not retention; see the note below the
table.

| Task | Evaluated model | Baseline | Well-formed failures | All-hint control | Contracts (A / C) | Per-model gate |
|---|---|---:|---:|---:|---|---|
| T2 scoped retrieval | Fable | 1/5 | 4/5 | 3/3 | v7 / v10 | Cleared |
| T14 uniform insufficiency | Fable | 0/5 | 5/5 | 3/3 | v11 / v10 | Cleared |
| T18 unstated domain constraint | GPT-5.6 Sol | 0/5 | 5/5 | 3/3 | v7 / v9 | Cleared; C5 critical |
| T21 decoupled axes | GPT-5.6 Sol | 0/5 | 5/5 | 3/3 | v8 / v10 | Cleared; C5 critical |
| T19 scoped gaps | GPT-5.6 Sol | 0/5 | 5/5 | 1/3 initial; 2/6 extended | v8 / v10 | Not cleared |

Contract ids are abbreviated; the full values are `2026-08-03-v7` through
`2026-08-04-v10` and are recorded per trial as `verifier_contract` in
`runs/*/result.json`. Baseline and control run under different contracts in every row,
which is permitted by the exception in `SPEC.md` section 9.2 rather than by the general
rule: re-running a five-seed baseline after each verifier correction was not affordable,
so a baseline is carried forward when the correction cannot reach an unhinted cohort.

That exception is checked rather than asserted. `python3 harness/rescore.py` replays
every stored baseline through the current verifiers and reports disagreements. Two
cohorts move and both are documented: T14's Fable baseline, 1/5 as recorded on v7
against 0/5 under v11 after the word-order correction in `docs/report.md` section 5;
and T19's Fable baseline, 9/15 against 15/15, on the row that did not clear the gate.
Every other cohort, and every all-hint control, scores identically under its recorded
contract and under the current one.

**No task in this table is retained.** Retention under `SPEC.md` section 9 requires the
same task to clear the gate for *both* target models, and each row above names a single
evaluated model: the other model passes that task. The Phase D human ceiling has also
not run. The four gate-clearing rows are therefore candidates, not completed benchmark
tasks.

The all-hint control is only run for the model that fails baseline, so
`harness/coverage.py` reports the opposite model's Phase C as incomplete for every row.
That is expected rather than a gap in the record.

T2's Phase C is meaningful only because of a correction made after its baseline was
known; `docs/report.md` section 5 records what changed and why the unhinted baseline is
unaffected.

See [the full report](../docs/report.md) for verifier corrections, rejected candidates,
and threats to validity.
