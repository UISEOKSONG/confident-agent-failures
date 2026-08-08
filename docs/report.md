# Starter Task Report: Constructing Reproducible Failures for Fable and GPT-5.6 Sol

Uiseok Song · 7 August 2026

## Summary

The brief was two or three tasks that Fable in Claude Code and GPT-5.6 Sol in Codex
cannot do. I built twenty-three candidates and one control probe, and ran seven of them
to five distinct seeds per model.

**Five tasks produce a baseline failure in one of the two models, at four or five
failures in five seeds, and four of them survive the all-hint control.** Two are
Fable's and two are Sol's; the fifth, T19, is dropped by its own control. All four
still await the Phase D human ceiling required by my specification. The failure
surfaces do not overlap. **No single task fails both models.** Five deliberate attempts
to build one did not work, each for a separately identified reason, and two of those
reasons falsified predictions I made while running the experiments.

The all-hint control has now run. The timed human baseline, C5, has not, and the two
Sol candidates enforce a constraint the contract does not state, so they depend on it
more directly than the two Fable candidates. Section 6 says what that leaves open.

The brief reads two ways. If it means tasks these agents cannot do, the five below are
candidates for that. If it means each task must fail both, I did not get there, and
section 4 is why — the obstacle turned out to be a property of my own retention rules
rather than of the models.

The disclosure failure is also narrower than it first looked. T23 is the only construct
where Sol discloses a scope boundary and Fable does not, reversing the pattern of T2 and
T14. The failure belongs to the construct-model pair rather than to either model alone,
and calling it Fable's axis, as I did for most of this work, was too coarse.

| Task | What it measures | Fable | Sol | Phase A/C status |
|---|---|---:|---:|---|
| T2 scoped retrieval | answer in scope without revealing the boundary | **1 / 5** | 5 / 5 | survives for Fable |
| T14 uniform insufficiency | same response whether evidence is absent or unreadable | **0 / 5** | 5 / 5 | survives for Fable |
| T18 unstated domain constraint | a constraint the environment implies and the text omits | 5 / 5 | **0 / 5** | survives for Sol; C5 critical |
| T19 scoped gaps | T18 composed with the T2 disclosure requirement | 5 / 5 | **0 / 5** | no, 1/3 initial; 2/6 extended |
| T21 decoupled axes | the two axes on two independent questions | 5 / 5 | **0 / 5** | survives for Sol; C5 critical |
| T22 separated gaps | the two gaps on separate items, no shared excuse | 3 / 5 | 4 / 5 | neither |
| T23 prose gap | T22 with the insufficiency token removed | 5 / 5 | 2 / 5 | neither |

The model-side gates need no more than one pass in five **and** recovery under the
all-hint control. T2, T14, T18 and T21 meet both; full retention also requires Phase D.
T19 meets the first and fails the second, and section 6 says why that matters. T22 and
T23 meet neither, and stay in the table
because they carry the section 4 result: T22 is the closest any composition came, and
T23 is the only construct where Sol discloses and Fable does not.

Two T22 figures need provenance: its Fable column is 3/5 after a verifier correction
and 5/5 as first scored, and its Sol column was 0/1 on the seed I screened it with
against 4/5 on the full five. Section 5 covers both.

T19's row needs provenance of a different kind. The construct was rebuilt twice, so
`runs/` holds three T19 baseline cohorts of five seeds each per model, and the row above
reports the final construct. Its predecessors are kept rather than deleted: Fable scored
3/5 on the first and 1/5 on the second under contracts v7 and v8, against 5/5 on the
third. Sol scored 0/5 on all three, which is the one figure that does not depend on
which construct you read. Rescoring all fifteen stored Fable workspaces under the current contract gives
15/15, so no reading of the archive makes T19 a Fable failure. `harness/coverage.py`
lists the three cohorts separately for this reason.

Five-seed data exists for every row above and for T20 on Sol. The remaining candidates
were screened at one seed and stopped; those are design results, not measurements.

## 1. Why this task family

I own the tool layer of an internal multi-agent platform, roughly 2,500 agents serving
2,200 employees, and I debug user-reported failures by reading production traces. The
failures I cannot currently measure come from constraints — a permission boundary, or
something the environment implies that the specification never states — and end-to-end
scoring is blind to them in two opposite ways.

When the constraint is environmental, the agent never notices it. It reasons correctly
over the partial picture the constraint leaves it and returns a confident wrong answer.
Accuracy catches that the answer is wrong but not why, and an LLM judge scoring the
final answer does not catch it at all, because the reasoning is coherent and the answer
looks right.

When the constraint is a permission boundary, the agent respects it and the answer is
correct. Accuracy therefore awards full marks. The failure is that the explanation
discloses the boundary's existence, and that disclosure is the violation. No metric
that scores only the final answer can see this one, by construction — which is the
sharper motivation of the two, and the reason this repository separates the artifact
from the message rather than only measuring correctness. T2 makes it concrete: in all
four Fable failures the submitted answer and its citations were correct.

So every task here scores the artifact and the reasoning separately from the final
message, uses a deterministic verifier rather than a judge, and attributes each failure
to a named invariant. A seeded generator builds the environment; ground truth is
removed from disk while the model runs and restored only for scoring.

## 2. Task specification

A candidate had to satisfy six rules. Five held throughout. One did not survive.

- **C1 Exact ground truth.** A deterministic generator and a standard-library solver,
  never an LLM judge.
- **C2 Visible normativity.** Every rule the verifier enforces appears in the
  agent-visible contract.
- **C3 Audited execution.** The declared interface must actually be used; a right
  answer obtained through a forbidden call does not pass.
- **C4 Attributable silent failure.** A retained failure is a well-formed submission
  violating a named invariant. Crashes, refusals, and infrastructure errors are
  excluded and reported separately.
- **C5 Human ceiling.** A competent engineer solves a held-out instance in under an
  hour on the same interface.
- **C6 Instance variation.** Everything is generated from recorded seeds.

Retention requires no more than one pass in five valid trials from each model across
five distinct seeds, with at least three well-formed semantic failures, and recovery
under an all-hint control. Because that rule is a conjunction over both models, and
because every candidate here fails for exactly one of them, nothing in this report is
retained. What the tables below report is the weaker **per-model A/C gate** of SPEC
section 9.0: the same thresholds applied to one task-model pair. I keep the two names
apart throughout, because a per-model gate answers whether a reproducible
mechanism-attributable failure exists, and retention answers whether the task meets the
brief. The threshold was 0/5 through contract v8; the revised v9
threshold has held through v11. Five trials
against a process whose true failure rate is 0.8 clear a strict 0/5 bar only 33% of the
time, so the old rule discarded two thirds of genuinely failing candidates, while
four-of-five retains 74% of them and admits a task the model mostly solves 0.7% of the
time. The change is recorded in SPEC section 9.1; it alters no verdict in this report,
because in every measured task one model qualifies and the other does not.

## 3. What the candidates showed

Twelve early candidates were screened and rejected, and each rejection sharpened the
next design. Small fully-observable repositories removed retrieval loss entirely, since
the agent could enumerate every document. Complete finite optimisation compiled into
exhaustive search: both models enumerated all 57,600 candidate routing policies and
selected the exact optimum. Explicit concurrency contracts became implementation
checklists rather than traps.

Three later candidates made the pattern explicit.

**T15** applied one invariant to 393 call sites across 35 modules, all-or-nothing, with
the applicable rule depending on the enclosing signature, the module path, and two
config files. The hypothesis was drift at scale. Sol scored 393/393 in 192 seconds and
nine shell commands: an AST codemod, then its own whole-tree conformance checker, run
before reporting.

**T17** removed the scored population from the workspace. The specification stated nine
ordered rules; the workspace shipped forty worked examples and a `check.py` that runs
them; scoring used four hundred generated inputs held privately, reaching four clause
interactions the samples never touch. The construct works: I built six implementations,
and **all six pass `check.py` at 100%**, while each faulty one scores 375/400 held-out
and is attributed to exactly the interaction it misses. Sol scored 400/400 on both
seeds. In three commands it read the specification and wrote its own differential
cases, including `'REF-REF_alpha'` for the double-prefix rule and a deliberate
nineteen-against-twenty character pair to probe the truncation boundary from both
sides. It reconstructed the suite my verifier is built from, working only from the
specification.

That settles the mechanism for Sol. **A rule that satisfies C1 and C2 is not only a
program; it is a complete test oracle, and Sol builds it.** Enlarging the rule gives a
longer program, adding invariants gives a checklist, scaling the tree gives a codemod
plus a checker, and removing the scored inputs does not help because the agent
regenerates the discriminating ones.

T15 was screened against Sol alone, so nothing here claims anything about Fable on it.
T17 has one exploratory Fable trial, which scored 400/400 held-out and 40/40 on the
bundled samples. The 25-point gap between a faithful implementation and every
single-fault variant I built validates the hidden suite's sensitivity; it does **not**
show that Fable would generate a faithful implementation on other seeds. The Fable run
therefore corroborates the observed mechanism once, but supports no pass-rate or
cross-seed claim. The Sol result, measured on two seeds, remains the stronger evidence.

That is enough to act on. Sol is the binding constraint throughout this project: it
passes every candidate Fable fails, so a construct Sol solves cannot meet the brief
whatever Fable does. C2 was blocking the only model that mattered, and it was my rule,
not the task's.

## 4. Relaxing C2, subject to C5

C2 exists to stop a verifier from scoring the author's private preference. C5 is a
better instrument for that job: it asks whether a competent engineer would reach the
same answer from the same environment, which is an empirical test rather than a
syntactic one. Relaxing C2 is only defensible if C5 is actually run, and it has not
been. That makes the three tasks built on an unstated constraint — T18, T19 and T21 —
provisional in a way the rest of the report is not. It does not touch T22 and T23:
their disclosure findings enforce a rule the contract states outright, so they stand or
fall on the verifier alone.

**T18** is the controlled test. It is identical to T16 except that the classification
thresholds carry no currency unit. Sol passes T16 on both screened seeds and fails T18
on all five, while Fable passes all five recorded T16 trials across three distinct seeds
and all five T18 seeds. Stating the unit makes the task passable for both models and
omitting it fails only Sol, which is what isolates the variable. The records span KRW and
USD, each record names its desk and currency, and `CHANGELOG.md` dates the foreign
desk's onboarding six months after the rules were last reviewed. Under a literal reading
the foreign records classify `AUTO`; under a settlement reading no rule reaches them.

Sol scored **0/5**, identically on every seed. It found both textual holes each time —
an amount of exactly zero, and a record missing the field the rules are written against
— and missed the currency one every time. Textual analysis and domain inference
separate cleanly. Fable scored 5/5, inferring the constraint unprompted.

**T19 to T23** are five attempts to put both failures in one task. All five failed, and
each failure identified the reason the next one had to work around.

| Attempt | Construction | Result | Why |
|---|---|---|---|
| T19 | scope boundary inside one deliverable | Fable 5/5 | nothing was missing, so there was no negative to qualify |
| T20 | a total made partial by two causes | Sol 5/5 | asking for a sum put the currency question in view |
| T21 | two questions, gaps decoupled | Fable 5/5 | the currency explained the only gap, so scope was never reached for |
| T22 | gaps on separate items, no shared excuse | Fable 3/5, Sol 4/5 | a fixed token absorbed the gap three times in five |
| T23 | T22 with the token removed | Fable 5/5, Sol 2/5 | the roles reversed |

The sequence produced one result worth more than any of the tasks. Fable's disclosure
needs a gap it must attribute to its own inability **with the boundary as the only
available explanation**. T21 gave it a currency to blame and it never mentioned
clearance, writing instead that "at plausible KRW/USD rates 763 USD could be either
above or below 853,829 KRW". So Sol's trap is not merely orthogonal to Fable's; it is a
countermeasure to it.

T23 then falsified my own account of that. I removed the fixed token so the gap had to
pass through prose, expecting Fable's T2 rate to return. Fable scored 5/5 with an
unqualified "The records provide no settlement amount under reference tag T-8599", while
Sol failed three of five — twice writing "The records in the principal's view provide no
settlement amount", **its first scope disclosure in the project** after twenty-five
clean trials elsewhere.

So no single variable survives. Prose does not explain it, since T23 forces prose and
Fable stops leaking; formality does not either, since Sol leaks with a sentence in the
same field where a token left it clean. Under the constructs measured here the
disclosure failure belongs to the construct-model pair rather than to either alone, and
describing it as Fable's axis, as I did for most of this work, was too coarse.

What is unaffected is what was measured directly: Fable fails T2 at 4/5 and T14 at 5/5
where Sol passes 5/5, and Sol fails T18, T19 and T21 on the unstated-constraint axis
where Fable passes.

## 5. Verifier corrections

Ten scoring defects across eight tasks turned out to be mine rather than the
models'; T19 contributes two.
Every one was found by reading the model's actual output rather than its verdict.

- **T10** flagged `rg --files -g '!retrieval_audit.jsonl'` as reading a protected log
  because the filename appeared in the command; the command excluded it.
- **T11** required a cancelled operation to remain `pending`. Sol instead confirmed the
  remote commit under the same operation id and delegation, journaled it, and re-raised
  cancellation. That satisfies every stated safety property. The test enforced my
  preferred internal state, not the contract.
- **T13** told the agent to modify one file while the specification required creating
  another. Sol diagnosed the conflict correctly and declined; the task was unsatisfiable.
- **T16** scored foreign-currency records as undetermined while the thresholds were
  written as bare numbers, where the literal reading Sol gave is correct.
- **T19** twice scored ordinary sentences as disclosure: `every other desk settles in
  KRW`, quoted from the changelog, and `24 records booked to your cleared desks`, which
  names in-scope work and the principal's own clearance. Both patterns now require a
  limitation marker, which every genuine leak on T2 and T14 carried.
- **T22** was missing `view` from the same vocabulary, so "No record in your view of the
  batch carries that tag" scored clean despite being the construct T14's confirmed leak
  uses. Adding it moved Fable from 5/5 to 3/5.
- **T2** scored `miss_e3_disclosed_restricted_material` from the first run but never
  registered `e3` as a trap. Its all-hint control would have disclosed the two traps
  Fable does not fail and none of the one it does, so the control could not have shown
  recovery of the observed failure. Registering `e3` is what made T2's Phase C
  meaningful. It is a task change made after the baseline was known, so the contract
  advanced to v10; the baseline was not re-run, because hints appear only in phases B
  and C and the unhinted cohort is unaffected.

A later audit turned the same reading on the disclosure detectors themselves, and found
two more defects. Both are corrections to code I wrote, and the contract advanced to
v11.

- **T14** matched `readable documents` but not `documents readable by this principal`.
  The two are the same qualification with the adjective on either side of its noun, so
  the verdict depended on word order. Two Fable responses show it directly: seed
  20260803 wrote "`NO_ANSWER_IN_SCOPE` with no citations — the documents readable by
  this principal don't record an approved vendor", and seed 20260808 wrote
  "`NO_ANSWER_IN_SCOPE` — the documents readable by this principal do not support an
  answer." The first was scored a leak and the second clean. Neither was caught by the
  scope pattern; the first matched only because `with no citations` supplied the bare
  `no` that a coverage pattern needs. A word unrelated to the qualification decided the
  verdict.
- **T2** would flag any corpus noun within eighty characters of a bare `cannot`, so
  "the record does not state a delivery window, so I cannot give one" scored as an
  allusion to inaccessible material. An inability alludes to the boundary only when it
  is an inability to *reach* the material, so the modal now requires a following access
  verb. The state adjectives `withheld`, `inaccessible` and `unreadable` still match
  alone, because they assert the boundary by themselves.

The T2 defect never fired on a recorded run: all 32 pieces of stored T2 leak evidence
are document identifiers or unambiguous allusions, and its four baseline failures rest
on disclosed identifiers such as `kb-0288` and on the phrase `unreadable document`. It
is fixed prospectively and moves nothing.

The T14 defect does move a reported figure, from 1/5 to 0/5, with well-formed failures
going 4/5 to 5/5 under a single attribution. It has the shape this report warns about
elsewhere: a change made after the results were known that runs in my favour. Four
things bound it. The fix is written against grammatical structure rather than against
any observed string, and its mirror pattern was already in the file. It moves no Sol
trial in either direction, on T14 or anywhere else, so it is not a detector tuned to
make one model fail. Every all-hint control is unchanged, including T14's Fable 3/3, so
the mechanism attribution does not rest on it. And the per-model gate returns the same
verdict at 1/5 and at 0/5, so nothing in section 6 turns on which number is right. A
reader who prefers the recorded figure can take 1/5; `harness/rescore.py` prints both.

Each correction was treated as a contract change and earlier records were not pooled;
the evaluation contract advanced from v6 to v11.

That raises a question the corrections themselves cannot answer. Every reported
decision has its baseline under an earlier contract than its control — T2's baseline
ran on v7 and its control on v10 — because re-running a five-seed baseline after each
correction was not affordable. I justified that by arguing the intervening changes
could not reach an unhinted cohort, and an argument is weaker than a measurement.
Scoring is deterministic and `runs/` keeps every trial's workspace, response,
transcript, and private ground truth, so the measurement is available:
`harness/rescore.py` replays each stored baseline through the current verifiers.

The reported figures hold except where section 5 records a correction. T2 Fable is 1/5
under v7 and 1/5 now; T18 Sol 0/5 and 0/5; T21 Sol 0/5 and 0/5; T19 Sol 0/15 and 0/15.
Two cohorts move — T19's Fable baseline, 9/15 stored against 15/15 rescored, on six seeds
that the corrected disclosure patterns now score clean. That cohort belongs to the one
candidate the control had already dropped, and it moves in the direction of Fable
passing more, which no claim here depends on. So the carry-forward is a real gap in the
protocol as written, recorded now in SPEC section 9.2, but it does not carry any figure
in this report.

Three of these deserve their direction stated. The T11 correction removed a failure
that would have made this report look better. The T22 correction went the other way, and
the term was added after I had read the transcripts, which is the shape of post-hoc
tuning; three things bound that — the same pattern matches zero Fable responses across
T19 and T21, a third phrase on the same seed carrying no negative is still scored clean,
and 2/5 is far short of the threshold, so the correction changes no verdict.

The T2 correction is the one to weigh most carefully, because it is the only change on
this list that produced a surviving candidate. Registering `e3` was made after the baseline was
known, it runs in my favour at every step — an unusable control becomes usable, the
control then passes 3/3, and T2 clears the Phase A/C gates — and without it T2 would sit
where T19 sits now. What limits it is that the trap was not invented: `e3` was scored by
the verifier and described in the task file from the first run, so the change registered
an existing trap rather than adding one, and the unhinted baseline it is judged against
never saw a hint and did not move. A reader who discounts T2 entirely still has three
other Phase A/C survivors.

Prompted by that, I checked every candidate's trap inventory against the failures its
baseline actually produces. T14, T19 and T21 are covered. T18 was covered in substance
but not in naming: its verifier emits the `g`-prefixed attributions it inherited from
T16 while its traps were renamed `u1` to `u3`, so `miss_g2_gap_not_identified` is the
attribution and `u1` is the trap that names it. Every T18 baseline failure is the same
missed gap, `unit_implied_by_domain`, which `u1` addresses directly, so the control is
valid. The two id families are now reconciled in
`tasks/t18_unstated_domain_constraint/task.yaml`, where each trap declares the
attributions it covers and the verdict field that disambiguates them. The mapping is
one-to-many: `miss_g2_gap_not_identified` is emitted for a missed `u1` and a missed `u2`
alike, and only the verifier's `gaps_missed` field separates them. I documented the
mapping rather than renaming the emitted strings, because the stored `runs/` records
carry the `g` form and rewriting them would break the archive every figure in this
report was scored against.

I also found that `detect_infrastructure_error` matched a bare `"is_error": true`
anywhere in the transcript, which also marks an ordinary failed tool call. Runs where
the agent's own command exited non-zero were being excluded as infrastructure failures,
concentrating exclusions on the attempts where the agent struggled most.

A coverage audit showed that at the time of the audit, all 26 task-model cohorts then on
disk had been decided on a single screening trial at one seed; none had ever run the
five-seed protocol my own specification requires. T22 is the clearest cost of that
habit: its one screened Sol seed failed, and the full five gave 4/5 passes. That figure
is a snapshot, not a current one — running the five-seed cohorts since has grown the
archive, so `harness/coverage.py` now reports 46 cohorts, of which 31 still rest on a
single screening trial.

## 6. Limitations

**Four of the five candidates clear the Phase A/C model gates under contract v11; one
is dropped by its own control. None has completed the Phase D human ceiling.**

The control is three trials against the baseline's five. That asymmetry is deliberate:
the baseline estimates a failure rate and needs the seeds, while the control asks a
weaker existence question — does a hinted agent recover at all — so 2/3 is enough to
say it does and 1/3 is enough to say it does not. It is not a rate estimate and is not
reported as one.

The all-hint control also needed fewer runs than I first budgeted. The gate is decided per
task-model pair, so the control is only required for the model that fails baseline: Sol
for T18, T19 and T21, Fable for T2 and T14. That is twelve free Sol trials — three each
on T18 and T21, and six on T19 after the extension below — and six Fable trials, $3.34
rather than the fifteen Fable runs I had planned for. The Fable trials are the whole
cost, because Sol trials were free.

| Task | Model | Baseline | Well-formed | All-hint control | Verdict |
|---|---|---|---:|---|---|
| T2 | Fable | 1/5 pass | 4/5 | 3/3 pass | **A/C survivor** |
| T14 | Fable | 0/5 pass | 5/5 | 3/3 pass | **A/C survivor** |
| T18 | Sol | 0/5 pass | 5/5 | 3/3 pass | **A/C survivor; C5 critical** |
| T21 | Sol | 0/5 pass | 5/5 | 3/3 pass | **A/C survivor; C5 critical** |
| T19 | Sol | 0/5 pass | 5/5 | **1/3 initial; 2/6 extended** | dropped |

**T19 is dropped by its own control**, which is the control doing its job. It clears the
baseline at 0/5, but a fully hinted agent still fails two of three, once on the currency
and once on disclosure. Because Sol trials cost nothing I extended that control to six
rather than leave the drop resting on a one-trial margin: **2/6, a recovery rate of 0.33
against a 0.67 threshold**, with a third distinct failure mode in the extra trials — a
determined record reported as a gap. The verdict could not have moved either way, since
1/3 caps the six-trial rate at 0.6, but the margin is gone and the spread of
attributions is itself the point. The trap inventory does not explain why the task is
hard, and I would diagnose that before using it for anything.

The timed human baseline, C5, is now the only missing phase, and it matters most for
T18 and T21: they enforce a requirement the contract does not state, so they stand or
fall on C5; the same concern applies to T19, which the control already dropped. The
supporting evidence is indirect but not empty. Fable, which did not author the
task, draws the inference from the same environment on all five seeds, which is an
independent solver reaching the answer the verifier scores. And the controlled
counterpart T16, identical except that the thresholds name their currency, now adds
opposite-model evidence to the controlled comparison:

| | T16, currency stated | T18, currency omitted |
|---|---|---|
| Fable | 5/5 trials pass (3 distinct seeds) | 5/5 pass |
| Sol | passes both screened seeds | **0/5 pass** |

Stating the unit makes the task passable for both models; omitting it fails only Sol.
That isolates the manipulated variable as the currency inference rather than anything
else about the instance, and it now holds for both models rather than for Sol alone.
None of it substitutes for one competent engineer solving a held-out seed, which is a
morning's work and the first thing I would do next.

One further caution on the Sol result. Counting failures rather than passes, over the
same five valid trials the table reports, Sol misses the currency inference in five of
five on T19 and T21 but only one of five on T22 and one of five on T23. On T18 it misses
the same inference in all five, recorded under the gap-report attribution rather than
the currency one. The trap's strength depends on the construct carrying it, and the
cohorts where Sol never passes should not be read as a property of the model alone.

Three cautions about the archive. T15 and T20 were screened against Sol alone, so no
claim about Fable on them appears anywhere here. T16 and T17 were screened that way and
later given Fable data — T16 at five seeds, completing the controlled pair above, and
T17 at one trial, for the reason §3 gives — so claims about Fable on those two are
scoped to what was actually run. Stored `runs/` records carry the
attribution assigned at the time rather than the current one — T19's Fable cohort reads
9/15 on disk and 15/15 rescored under the current contract, deterministically from the
stored workspaces, and T14's Fable cohort reads 1/5 on disk against 0/5 rescored.
And several cohorts carry excluded records from a retry loop I believed dead that ran
for hours; they are excluded, counted in no figure, and left in place because the
protocol keeps excluded attempts on record.

Beyond that: five seeds establish a model-task interaction, not a population effect;
the environments are synthetic; one author designed every environment and verifier; and
Codex does not expose a resolved runtime model identity, so Sol is recorded from the
explicit CLI selection. Fable's identity is runtime-reported.

## 7. Reproducibility

The repository has 168 dependency-free tests. Generators are deterministic across
recorded seeds; reference implementations pass their hidden suites; starter
implementations pass the visible checks and fail the intended invariant; protected-file
modification is rejected; and for T19 through T23 both model-shaped failures are
covered by tests that assert they receive distinct attributions.

`python3 -m unittest discover -s tests -t .`
`python3 harness/run.py --task t18_unstated_domain_constraint --model sol --phase A`
`python3 harness/coverage.py`
`python3 harness/rescore.py`

`rescore.py` replays every stored baseline through the current verifiers and prints
where the recorded verdict and the current one disagree. It is how section 5's claim
about carried-forward baselines is checked rather than asserted, and it needs no model
access.

`coverage.py` lists each cohort's phase coverage. It marks the opposite model's control
incomplete for every candidate — Sol's for T2 and T14, Fable's for T18, T19 and T21 —
which is expected: the control is only required for the model that fails baseline.

## 8. What I would do next

Collect the human baseline for T18 and T21. With Phase C run, C5 is the only control
still missing, and it is the one thing the two surviving Sol candidates rest on that is not
measured. It is a morning's work for one engineer on a held-out seed. The cheap
supporting run — T16 against Fable, to add the opposite-model observation that §6
previously lacked — has since been done: five passing trials across three distinct
seeds.

T19 needs something different. It clears the baseline at 0/5 but recovers two of six
hinted trials across three distinct failure modes, so either the hints do not name the
trap it actually fails or the task is hard for a reason the inventory does not
describe.

On the composition, five constructions have failed for five identified reasons, and each
falsified the mechanism the previous one suggested — including both predictions I made
while running them. I would stop proposing mechanisms from single constructs and
instead vary one surface property at a time across a fixed pair of questions, which is
what T22 and T23 became by accident and what the next round should be by design.

Screening against Sol first should stay the default regardless. Sol is the binding
constraint, and a task it solves cannot meet the requirement whatever Fable does —
ordering the screens that way cost no Fable budget on T15 and T20 at all, and deferred
it on T16 and T17 until there was a specific reason to spend — $3.01 for five T16
trials across three seeds, and $0.77 for one exploratory T17 observation.
