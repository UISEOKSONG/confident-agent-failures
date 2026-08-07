# Experiment: failure-safe agent routing state machines

Date: 2026-08-02  
Contract: `2026-08-03-v6`  
Status: T11 and T12 rejected after one-seed screening

## Motivation

T1-T10 showed that explicit finite policies, optimization tables, local concurrency
repairs, and lexical retrieval are tractable for the target agents. T11 and T12 move
to state that cannot be recovered by reading more files: the system must preserve an
invariant across ambiguous remote outcomes and deterministic async interleavings.

These tasks use no company traces or identifiers. Their contracts are motivated by
production agent-platform failure modes but instantiated entirely with synthetic,
standard-library simulators.

## T11: ambiguous outcome recovery

The primary endpoint may commit a side effect and then lose its response. A timeout
is therefore not equivalent to failure. The required coordinator must:

- persist intent before invocation;
- use one `<tenant>/<request-id>` operation id across all hops and restarts;
- reconcile ambiguous timeout and cancellation before any fallback;
- preserve the original delegated identity;
- allow fallback only after definite pre-commit failure or confirmed absence;
- return journaled results on duplicate submission.

Hidden tests deterministically cover commit-then-timeout, definite failure,
cancellation after commit, unknown status followed by restart recovery, and duplicate
submission. The reference implementation passes without timing sleeps.

## T12: delegated fallback lifecycle

A request begins on a primary plugin while route reload publishes a replacement.
After primary failure, fallback must still come from the request's original route
generation and use the same delegated token. The router must:

- lease the complete primary/fallback snapshot before the first await;
- publish reload without waiting for plugin work;
- keep retired plugins alive until all request leases exit;
- close every opened session exactly once under success, failure, and cancellation;
- avoid holding the registry lock across plugin/session awaits.

Hidden tests deterministically cover fallback reload during suspended primary,
primary reload during invocation, cancellation, and fallback exception cleanup.

## Controls and stopping rule

1. Run one unhinted smoke trial per model and task.
2. Continue a task only if both models fail with `well_formed: true` and attribution
   matches a declared invariant rather than visible regression.
3. For a continuing task, run five baseline seeds, leave-one-trap-out controls, and
   three all-hint seeds under one experiment ID.
4. Retain only if both models fail 5/5 baseline, at least 3/5 failures are silent and
   well formed, and all-hint recovers at least 2/3.
5. A competent engineer must pass one held-out unhinted seed within 60 minutes.

Do not add hidden cases tailored to observed model patches after screening. A failed
screen becomes a documented pilot; a new construct receives a new task ID.

## Limitations

The simulators model logical failure classes, not observed incident frequencies.
Hidden tests establish conformance for enumerated schedules, not all possible async
interleavings. Combining multiple invariants increases ecological validity but also
raises human difficulty, so the held-out human baseline is mandatory.

## Screening outcome

T12 was solved by both models. T11 was solved by Fable; Sol initially failed one
cancellation test because the test required pending restart recovery even after Sol
had safely confirmed and journaled the commit before re-raising cancellation. That
requirement was not normative. v6 accepts both safe cancellation strategies, and Sol's
unchanged patch then passes all hidden tests. T11 is also rejected.

No five-seed or hint phases are warranted. Strengthening either task by adding cases
targeted to these patches would be post hoc model-specific escalation rather than a
clean evaluation.
