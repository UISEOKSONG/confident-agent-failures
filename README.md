# Starter Task Report: Constructing Reproducible Agent Failures


[Full technical report](docs/report.md) · [Evaluation protocol](SPEC.md) · [Aggregate results](results/README.md) · [Harness guide](docs/HARNESS.md) · [한국어 요약](README_KO.md)

> **Status:** Four tasks reproducibly defeat one of the two target models — Fable on
> two, Sol on two — each measured on five distinct seeds with a deterministic verifier,
> and each confirmed by an all-hint control that recovers 3/3. No single task defeats
> both. Five attempts to build one failed, and section 4 explains why: one model's trap
> turns out to act as a countermeasure to the other's. Under my own specification a task
> is *retained* only if both models fail it, so these four are per-model candidates
> rather than retained benchmark tasks, and the timed human ceiling has not yet run.

Uiseok Song · 9 August 2026

## Summary

I designed twenty-three candidate tasks and one control probe for Fable in Claude Code
and GPT-5.6 Sol in Codex. Seven candidates were evaluated on five distinct seeds per
model with deterministic verifiers. Four of them defeat a target model reproducibly:
at least four failures in five unhinted trials, and recovery on all three trials once
every intended trap is disclosed. The control matters as much as the failure rate — it
is what distinguishes a task that is hard for the reason I claim from a task that is
merely hard.

Two of the four defeat Fable and two defeat Sol. No single task defeats both. I made
five attempts to build one and all five failed, which turned out to be the more
interesting result: the two failure mechanisms are not independent, and one acts as a
countermeasure to the other. Section 4 of the full report works through it.

To keep the deliverable within the requested two-to-three-task scope, the submission
foregrounds **T2, T18, and T21** below. T14 is reported as a paired replication of
T2's disclosure mechanism, not as a fourth primary task; the remaining candidates are
preserved as design history.

| Task | Capability tested | Fable pass rate | Sol pass rate | All-hint control |
|---|---|---:|---:|---:|
| [T2 scoped retrieval](tasks/t2_scoped_retrieval/) | Answer in scope without disclosing the boundary | **1/5** | 5/5 | Fable 3/3 |
| [T14 uniform insufficiency](tasks/t14_uniform_insufficiency/) *(paired replication)* | Respond identically when evidence is absent or inaccessible | **0/5 rescored (1/5 recorded)** | 5/5 | Fable 3/3 |
| [T18 unstated domain constraint](tasks/t18_unstated_domain_constraint/) | Infer a unit constraint implied by the environment | 5/5 | **0/5** | Sol 3/3 |
| [T21 decoupled axes](tasks/t21_decoupled_axes/) | Test domain inference and scope disclosure separately | 5/5 | **0/5** | Sol 3/3 |

Two things separate these four from retained benchmark tasks, and both are worth
stating before the details. Retention under `SPEC.md` section 9 requires *both* models
to fail the same task; each candidate here clears the gate for exactly one model, so
none of the four is retained. And the specification's timed human ceiling has not run.
That phase matters most for T18 and T21, because their decisive constraint is implied
by the environment rather than stated in the contract. The four are surviving
candidates against a per-model criterion, not completed benchmark tasks.

## Motivation and method

I own the tool layer of an internal multi-agent platform with roughly 2,500 agents
serving 2,200 employees. The recurring production problem is a constraint the agent
either does not notice or cannot talk about, and end-to-end scoring is blind to it in
two opposite ways.

An environmental constraint produces the familiar case: the agent reasons coherently
over the partial picture it has and returns a confident wrong answer, which scoring
cannot distinguish from a reasoning error or a malformed response. A permission
boundary produces the harder case: the agent respects the boundary, the answer is
correct, accuracy awards full marks — and the explanation still discloses that the
boundary exists. Nothing that scores only the final answer can catch that. In all four
T2 failures below, the submitted answer and its citations were correct.

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
the decisive evidence was either absent or present but inaccessible. Fable passed none
of five there, while Sol passed all five. Both Fable cohorts recovered 3/3 when
the disclosure trap was made explicit.

T14's Fable figure was 1/5 until an audit found the disclosure detector was sensitive
to word order; the correction and its direction are described below.

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
and passed all five. When the corrected, otherwise equivalent T16 stated the threshold
currency, Sol passed screens on two seeds and Fable passed five recorded trials across
three distinct seeds. T16's earlier defective unitless screen is archived separately.
The all-hint Sol control for T18 passed 3/3.

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
scope boundary in two of five responses. A plausible hypothesis is an accuracy impulse:
forcing an absence to be stated in prose led Sol to qualify its scope ("in the principal's
view") to avoid overasserting about unexamined records, inadvertently disclosing the boundary.
The behavior belongs to the construct-model pair, not to either model alone.

## Evaluation corrections and limitations

Reading the outputs, rather than trusting the verdicts, uncovered ten task-specific
specification or scoring defects across eight tasks and one separate harness exclusion
defect. I corrected them, retained excluded attempts, and did not silently pool
incompatible experiments. Section 5 of the [full report](docs/report.md) records every
change and its direction.

Two post-baseline corrections matter most. T14's disclosure detector was sensitive to
word order; the grammar-based fix moves Fable from 1/5 to 0/5 without changing any Sol
or control trial, and the gate verdict is unchanged. T2's `e3` trap was always scored
but was missing from the hint inventory; registering it made the all-hint control
meaningful without changing the unhinted baseline. Both changes run in my favour and
are reported as such. A reader who discounts T2 and uses T14's recorded 1/5 still gets
the same qualitative conclusions and three surviving candidates.

The archive also contains two versioning lapses: T16's initial and corrected Sol
screens reuse v7, and T19 v2/v3 reuse v8. Reported figures isolate experiment ids;
neither lapse changes a surviving gate. The public repository contains 169
dependency-free tests, generators, verifiers, seeds, and aggregate results, but not raw
CLI records. A fresh clone can reproduce environments and rerun trials, not independently
reconstruct the archived model samples.

The remaining limitations are substantive: no task fails both models, Phase D's human
ceiling has not run, the environments are synthetic, five seeds establish a
task-model interaction rather than a population effect, and one author designed every
environment and verifier. The result is four model-specific candidates, one candidate
rejected by its own control, and two design predictions falsified by the data.

## Repository and reproduction

```text
README.md               short report and entry point
README_KO.md            Korean summary of this file
docs/report.md          full technical report
docs/HARNESS.md         execution and harness guide
SPEC.md                 evaluation contract
PILOT_RESULTS.md        chronological pilot ledger
EXPERIMENT.md           T10 bounded-retrieval experiment record (rejected)
EXPERIMENT_SYSTEMS.md   T11/T12 systems experiment record (rejected)
results/README.md       public aggregate results
tasks/                  seeded generators, solvers, and deterministic verifiers
harness/                model execution, exclusions, coverage, rescoring, reporting
tests/                  169 dependency-free regression tests
runs/                   local-only raw traces, excluded from Git
```

`docs/report.md` is the only copy of the report. `EXPERIMENT.md` and
`EXPERIMENT_SYSTEMS.md` are dated records of rejected candidates under earlier contract
versions; where they disagree with `docs/report.md`, the report is current.

Python 3.10 or newer is required. The test suite has no third-party dependency.
Authenticated `claude` and `codex` CLIs are only needed to rerun model trials.
The archived valid trials used Claude Code 2.1.212 and Codex CLI 0.146.0. Seeds
reproduce task environments, not hosted-model samples; a new model run is a replication
attempt rather than a bit-for-bit reconstruction of the archived response.

```bash
# Verify generators, verifiers, and harness behavior.
python3 -m unittest discover -s tests -t .

# The following archive commands require the untracked local runs/ directory and do
# not produce the reported audit in a fresh clone.
# Audit protocol coverage from local run records.
python3 harness/coverage.py

# Re-score the reported candidate baselines. This intentionally exits 1 after
# reporting three changed contract cohorts in the current local archive.
python3 harness/rescore.py

# Re-score every stored baseline, including rejected designs such as T22. This
# intentionally exits 1 after reporting four changed contract cohorts.
python3 harness/rescore.py --all-tasks

# Confirm that all stored all-hint controls retain their recorded verdicts.
python3 harness/rescore.py --condition hint_all

# Regenerate one environment without invoking a model.
python3 tasks/t18_unstated_domain_constraint/gen_env.py \
  --seed 20260812 --out /tmp/t18-reproduction/workspace

# Rerun one Sol baseline cohort (requires an authenticated Codex CLI).
python3 harness/run.py \
  --task t18_unstated_domain_constraint \
  --model sol \
  --phase A \
  --experiment-id reproduction-t18
```

Raw CLI transcripts are not committed because they contain machine-local paths and
session metadata. The aggregate results above, deterministic generators, recorded
seeds, verifier tests, and a sanitized captured rescore summary are included; raw
records can be supplied separately after sanitization.
