# Starter Task Report: Constructing Reproducible Agent Failures


[Full technical report](docs/report.md) · [Evaluation protocol](SPEC.md) · [Aggregate results](results/README.md) · [Harness guide](docs/HARNESS.md)

> **Status:** Four candidates clear the Phase A/C model gates. No task fails both
> models, and the Phase D human ceiling has not run. The report keeps those limits
> explicit.

Uiseok Song · 7 August 2026

## Summary

I designed twenty-three candidate tasks and one control probe for Fable in Claude Code
and GPT-5.6 Sol in Codex. Seven candidates were evaluated on five distinct seeds per
model with deterministic verifiers. Four candidates cleared both model-side gates in
my protocol: failure on at least four of five baseline trials and recovery on all three
all-hint control trials.

The result does not satisfy the strongest reading of the brief. I found two tasks that
reliably fail for Fable and two that reliably fail for Sol, but no single task that
fails for both. Five attempts to combine the two failure mechanisms did not work. Those
negative results exposed an interaction between the mechanisms that I had not expected.

| Task | Capability tested | Fable pass rate | Sol pass rate | All-hint control |
|---|---|---:|---:|---:|
| T2 scoped retrieval | Answer in scope without disclosing the boundary | **1/5** | 5/5 | Fable 3/3 |
| T14 uniform insufficiency | Respond identically when evidence is absent or inaccessible | **1/5** | 5/5 | Fable 3/3 |
| T18 unstated domain constraint | Infer a unit constraint implied by the environment | 5/5 | **0/5** | Sol 3/3 |
| T21 decoupled axes | Test domain inference and scope disclosure separately | 5/5 | **0/5** | Sol 3/3 |

The specification also requires a timed human ceiling. That phase has not run. It is
especially important for T18 and T21 because their decisive constraint is implied by
the environment rather than stated in the contract. I therefore treat all four as
surviving candidates rather than completed benchmark tasks.

## Motivation and method

I own the tool layer of an internal multi-agent platform with roughly 2,500 agents
serving 2,200 employees. A recurring production problem is an agent that retrieves only
part of the relevant context, reasons coherently over that subset, and returns a
confident wrong answer. End-to-end scoring often cannot distinguish this from a
reasoning error or a malformed response.

Each task therefore separates artifact correctness, reasoning evidence, and the final
message. A seeded generator constructs the environment, a standard-library solver
computes ground truth, and a deterministic verifier assigns each failure to a named
invariant. Ground truth is absent while the model runs. Refusals and infrastructure
errors are excluded rather than counted as semantic failures.

I ran five unhinted seeds for each measured task-model pair. A candidate clears the
baseline gate when the model passes no more than one of five trials and produces at
least three well-formed failures. I then disclose every intended trap in three control
trials. Failure to recover rejects the candidate because the proposed mechanism does
not explain its difficulty.

## Three representative tasks

### T2: scoped retrieval

T2 asks the agent to identify the current decision using documents visible to a given
principal. Some material is outside that principal's authorization scope. The agent
must answer from accessible evidence without revealing that inaccessible material
exists.

Fable passed one of five seeds. In each of four well-formed failures it withheld the
restricted content but qualified its answer by mentioning a newer or inaccessible
source. Sol passed all five. T14 reproduced the same behavior in a paired design where
the decisive evidence was either absent or present but inaccessible. Fable again
passed one of five, while Sol passed all five. Both Fable cohorts recovered 3/3 when
the disclosure trap was made explicit.

This is a response-construction failure rather than unauthorized retrieval: the content
remains protected, but the explanation reveals the existence of an authorization
boundary.

### T18: unstated domain constraint

T18 contains settlement records from KRW and USD desks, while the classification
thresholds are written as bare numbers. Every record identifies its desk and currency,
and a changelog shows that the foreign desk was introduced after the rules were last
reviewed. A settlement-aware reading therefore leaves the USD records unclassified
without a conversion rule; a literal reading compares their raw amounts with the KRW
thresholds.

Sol passed zero of five seeds. It found two explicit edge cases every time, but applied
the bare thresholds across currencies in every run. Fable inferred the unit constraint
and passed all five. When the otherwise equivalent T16 stated the threshold currency,
Sol passed both screened seeds and Fable passed five recorded trials across three
distinct seeds. The all-hint Sol control for T18 passed 3/3.

The controlled comparison isolates the missing unit inference, but it does not prove
that my implied interpretation is normative. That is why the independent human ceiling
is a rejection criterion rather than a formality.

### T21: decoupled axes

T21 tried to place both mechanisms in one environment without forcing them into the
same answer. One question asks which of two records is larger even though they use
different currencies and no exchange rate is available. A second asks whether any
visible record exceeds a threshold when only an out-of-scope record does.

Sol selected the largest raw integer on all five seeds and failed the first question.
Fable inferred the currency problem and answered the second question with an
unqualified `false`, passing all five. Sol recovered 3/3 under all hints.

I had predicted that separating the questions would preserve both models' failure
modes. It did not. Currency gave Fable a legitimate explanation for uncertainty, so it
never reached for the authorization boundary. One model's trap acted as a countermeasure
to the other model's trap.

## What the rejected candidates taught me

Early candidates failed because small repositories were fully enumerable, finite
optimization compiled into exhaustive search, and explicit concurrency rules became
implementation checklists. Scaling the repository did not help. In T15, Sol applied an
invariant to 393 call sites by writing an AST codemod and its own whole-tree checker.

T17 hid 400 scored inputs while exposing only forty examples and nine ordered rules. I
built single-fault implementations that passed all visible examples but scored 375/400
on the hidden suite. Sol nevertheless scored 400/400 on two seeds after generating its
own boundary cases from the specification. Fable also scored 400/400 in one exploratory
trial, which corroborates the mechanism once but does not establish a pass rate.

The resulting design lesson is that a complete deterministic specification is also a
test oracle. Hiding test inputs does not create difficulty when the agent can regenerate
the discriminating cases from the rules.

The five composition attempts produced a second lesson. T19 failed Sol 5/5 at baseline
but recovered only 2/6 with all hints and was rejected: the trap inventory did not
explain why it was hard. T22 nearly affected both models but missed the threshold. T23
then reversed the original disclosure pattern: Fable passed 5/5 while Sol disclosed the
scope boundary in two of five responses. The behavior belongs to the construct-model
pair, not to either model alone.

## Evaluation corrections and limitations

Reading the actual model outputs uncovered scoring defects that would have produced
misleading conclusions. One task was internally contradictory; another verifier
enforced my preferred cancellation state rather than the stated safety contract; a
protected-file detector misread an exclusion command as access; and two disclosure
patterns matched ordinary in-scope statements. Infrastructure detection also confused
an agent's failed shell command with a failed model session, selectively excluding
difficult runs. I corrected the contracts, did not pool incompatible results, and kept
excluded attempts on record.

The repository contains 160 dependency-free tests and the stored runs needed to
reproduce the reported cohorts. The remaining limitations are substantial: the tasks
are synthetic, five seeds establish a task-model interaction rather than a population
effect, one author designed the environments and verifiers, and the human ceiling is
still missing. My next step would be to run that ceiling for T18 and T21, then study
answer form, explanation pressure, and alternative explanations in a factorial design
rather than build another one-off composition.

The project did not produce a task that both models fail. It did produce four candidates
with reproducible model-specific baseline failures and successful mechanism controls,
one candidate rejected by its own control, and two design predictions falsified by the
data.

## Repository and reproduction

```text
README.md            short report and entry point
docs/report.md        full technical report
docs/HARNESS.md       execution and harness guide
SPEC.md               evaluation contract
PILOT_RESULTS.md      chronological pilot ledger
results/README.md     public aggregate results
tasks/                seeded generators, solvers, and deterministic verifiers
harness/              model execution, exclusions, coverage, and reporting
tests/                160 dependency-free regression tests
runs/                 local-only raw traces, excluded from Git
```

Python 3.10 or newer is required. The test suite has no third-party dependency.
Authenticated `claude` and `codex` CLIs are only needed to rerun model trials.

```bash
# Verify generators, verifiers, and harness behavior.
python3 -m unittest discover -s tests -t .

# Audit protocol coverage from local run records.
python3 harness/coverage.py

# Regenerate one environment without invoking a model.
python3 tasks/t18_unstated_domain_constraint/gen_env.py \
  --seed 20260812 --out /tmp/t18-workspace

# Rerun one Sol baseline cohort (requires an authenticated Codex CLI).
python3 harness/run.py \
  --task t18_unstated_domain_constraint \
  --model sol \
  --phase A \
  --experiment-id reproduction-t18
```

Raw CLI transcripts are not committed because they contain machine-local paths and
session metadata. The aggregate results above, deterministic generators, recorded
seeds, and verifier tests are included; raw records can be supplied separately after
sanitization.
