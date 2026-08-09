# Harness and experiment guide

The harness generates isolated task workspaces, invokes one target CLI per trial,
restores verifier-only ground truth after the model exits, and records the response,
transcript, verdict, model identity, exclusions, and usage metadata.

## Requirements

- Python 3.10 or newer.
- No third-party Python package is required.
- Authenticated `claude` and `codex` CLIs are needed only for model trials.

The archived valid trials used Claude Code 2.1.212 and Codex CLI 0.146.0. Task seeds
reproduce the generated environments, but hosted model behavior is not version-pinned;
a rerun is therefore a replication attempt, not a bit-for-bit response reconstruction.

Claude JSON reports the runtime model identity. Codex JSONL does not expose the
resolved runtime model, so Sol records the configured `--model` value with identity
source `configured_cli`.

## Verify the repository

```bash
python3 -m unittest discover -s tests -t .
python3 harness/coverage.py
```

## Generate an environment

Generators place model-visible files under the requested output directory and keep
ground truth available to the harness only for scoring.

```bash
python3 tasks/t18_unstated_domain_constraint/gen_env.py \\
  --seed 20260812 --out /tmp/t18-reproduction/workspace
```

## Run a model cohort

```bash
python3 harness/run.py \\
  --task t18_unstated_domain_constraint \\
  --model sol \\
  --phase A \\
  --experiment-id reproduction-t18
```

Use `--model fable`, `--model sol`, or `--model all`. An experiment id defines one
cohort and should not be reused across incompatible verifier contracts.

Historical T16 and T19 records predate consistent enforcement of that rule and reused
contract ids across incompatible revisions. `coverage.py` cannot separate those rows;
the full report identifies the corrected/final experiment ids used in reported figures.

## Evaluation phases

| Phase | Purpose | Default trial count |
|---|---|---:|
| `S` | One-seed screening; never a retention verdict | 1 |
| `A` | Unhinted baseline across distinct seeds | 5 |
| `B` | Leave-one-defect-out attribution | 3 per condition |
| `C` | All-hint recovery control | 3 |
| `O` | Retrieval oracle conditions for bounded retrieval tasks | 3 per condition |
| `all` | Run the applicable full sequence | task-dependent |

The Phase A threshold is no more than one pass in five valid trials, with at least
three well-formed semantic failures. Phase C requires at least two passes in three.
The full protocol and Phase D human ceiling are defined in [`SPEC.md`](../SPEC.md).

## Exclusions and retries

Authentication failures, infrastructure failures, refusals, and model-identity
mismatches are excluded rather than counted as semantic failures. Excluded attempts
remain on disk and are retried only to the configured cap. An agent command that exits
non-zero is not by itself an infrastructure failure.

## Local run records

Raw records are written under `runs/<experiment-id>/...`. They are intentionally
ignored by Git because transcripts contain machine-local paths and session metadata.
Do not publish them without sanitization. Public aggregate results are in
[`results/README.md`](../results/README.md).
