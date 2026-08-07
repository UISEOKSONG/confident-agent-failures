# Public result summary

This directory contains aggregate results suitable for the public repository. Raw
`runs/` transcripts are intentionally not committed because CLI streams contain
machine-local paths, session identifiers, and other runtime metadata. They remain
available locally and can be regenerated from the recorded seeds.

## Phase A and C results

Pass counts are model passes, so lower baseline values indicate more frequent failure.

| Task | Evaluated model | Baseline | Well-formed failures | All-hint control | Status |
|---|---|---:|---:|---:|---|
| T2 scoped retrieval | Fable | 1/5 | 4/5 | 3/3 | Clears A/C |
| T14 uniform insufficiency | Fable | 1/5 | 4/5 | 3/3 | Clears A/C |
| T18 unstated domain constraint | GPT-5.6 Sol | 0/5 | 5/5 | 3/3 | Clears A/C; C5 critical |
| T21 decoupled axes | GPT-5.6 Sol | 0/5 | 5/5 | 3/3 | Clears A/C; C5 critical |
| T19 scoped gaps | GPT-5.6 Sol | 0/5 | 5/5 | 1/3 initial; 2/6 extended | Dropped |

The Phase D human ceiling required by `SPEC.md` has not run. Accordingly, the four
A/C survivors are candidates rather than completed benchmark tasks.

See [the full report](../docs/report.md) for verifier corrections, rejected candidates,
and threats to validity.
