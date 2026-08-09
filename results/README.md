# Public result summary

This directory contains aggregate results suitable for the public repository. Raw
`runs/` transcripts are intentionally not committed because CLI streams contain
machine-local paths, session identifiers, and other runtime metadata. They remain
available locally. Recorded seeds deterministically regenerate task environments, but
model outputs require new trials and need not be identical.

## Phase A and C results

Pass counts are model passes, so lower baseline values indicate more frequent failure.
Each row reports one task-model pair against the **per-model A/C gate** defined in
`SPEC.md` section 9.0. Clearing that gate is not retention; see the note below the
table.

| Task | Evaluated model | Baseline | Well-formed failures | All-hint control | Contracts (A / C) | Per-model gate |
|---|---|---:|---:|---:|---|---|
| T2 scoped retrieval | Fable | 1/5 | 4/5 | 3/3 | v7 / v10 | Cleared |
| T14 uniform insufficiency | Fable | 0/5 rescored (1/5 recorded) | 5/5 | 3/3 | v7 (rescored v11) / v10 | Cleared |
| T18 unstated domain constraint | GPT-5.6 Sol | 0/5 | 5/5 | 3/3 | v7 / v9 | Cleared; C5 critical |
| T21 decoupled axes | GPT-5.6 Sol | 0/5 | 5/5 | 3/3 | v8 / v10 | Cleared; C5 critical |
| T19 scoped gaps | GPT-5.6 Sol | 0/5 | 5/5 | 1/3 initial; 2/6 extended | v8 / v10 | Not cleared |

The T19 row is the final `t19v3-sol` construct. T19 v2 also carries v8 because an early
revision failed to advance the contract; the full report records that versioning lapse
and keeps the experiment ids separate.

Recorded run contract ids are abbreviated; their full values range from
`2026-08-03-v7` through `2026-08-04-v10` and appear per trial as
`verifier_contract` in `runs/*/result.json`. The v11 value in the T14 row names the
current verifier used for rescoring, not a recorded run contract. Baseline and control
run under different contracts in every row, which is permitted by the exception in
`SPEC.md` section 9.2 rather than by the general rule: re-running a five-seed baseline
after each verifier correction was not affordable, so a baseline is carried forward
when the correction cannot reach an unhinted cohort.

That exception is checked rather than asserted in the local archive.
`python3 harness/rescore.py` replays the reported-task baselines through the current
verifiers and reports disagreements. Two task-model pairs move across three stored-contract
cohorts, and both are documented: T14's Fable baseline, 1/5 as recorded on v7
against 0/5 under v11 after the word-order correction in `docs/report.md` section 5;
and T19's Fable baseline, 9/15 against 15/15, on the row that did not clear the gate.
Every other baseline cohort scores identically under its recorded contract and under
the current one. A separate `--condition hint_all` audit confirms that all five control
cohorts also retain their recorded verdicts. Sanitized captures are available for the
reported cohorts in [`rescore-summary.txt`](rescore-summary.txt) and for the broader
archive, including T22, in [`rescore-all-summary.txt`](rescore-all-summary.txt). A fresh
clone does not contain the raw records needed to regenerate them.

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
