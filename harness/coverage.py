#!/usr/bin/env python3
"""Report how much of the SPEC section 9 protocol each task/model has actually run.

`run.py --report` prints INCOMPLETE for any cohort that has not met the retention
requirement, but it does not distinguish "screened once" from "nearly finished".
A screening pass (phase S, one trial, one seed) is not evidence about a task; the
retention decision needs phase A at five distinct seeds. This report makes the gap
explicit so a candidate is never rejected on a single observation.

Trials are grouped by evaluation contract, never summed across contracts. SPEC section 9
states that older contract versions are never pooled with current results, so a cohort
that was re-run after a verifier correction has one row per contract, and only the
newest contract counts toward coverage. Summing them would overstate coverage: T19's
Fable baseline, for example, holds three five-seed cohorts under two contracts, and
reporting that as 15/5 would claim the protocol was exceeded when no single contract
ran more than ten trials.

Two early revisions reused a contract id: T16's Sol screens before and after its unit
correction, and T19 v2 and v3. This report cannot infer a construct boundary absent
from the stored contract metadata, so it pools those same-id records. SPEC section 9.2
and the full report identify the affected experiment ids; reported decisions use those
explicit boundaries rather than the pooled coverage row.

Usage: python3 harness/coverage.py [--runs ./runs] [--all-contracts]
"""
import argparse
import collections
import json
import os
import re
import sys


REQUIRED = (
    ("A", "baseline", 5, 5),
    ("C", "hint_all", 3, 3),
)

UNKNOWN_CONTRACT = "(unrecorded)"


def contract_order(contract):
    """Sort key for contract ids of the form YYYY-MM-DD-vN.

    The numeric suffix is compared as an integer so that v10 sorts after v9 rather
    than between v1 and v2. Unrecorded contracts sort first, since every record that
    carries one postdates the records that do not.
    """
    if contract == UNKNOWN_CONTRACT:
        return ("", 0)
    match = re.match(r"^(.*)-v(\d+)$", contract)
    if not match:
        return (contract, 0)
    return (match.group(1), int(match.group(2)))


def load(runs_dir):
    records = []
    for dirpath, _, files in os.walk(runs_dir):
        if "result.json" not in files:
            continue
        with open(os.path.join(dirpath, "result.json"), encoding="utf-8") as handle:
            records.append(json.load(handle))
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runs",
        default=os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "runs"),
    )
    parser.add_argument(
        "--all-contracts",
        action="store_true",
        help="also list superseded contracts, which do not count toward coverage",
    )
    args = parser.parse_args()

    records = load(args.runs)
    if not records:
        print("no runs found under %s" % args.runs)
        return 0

    trials = collections.defaultdict(list)
    for record in records:
        if record.get("excluded"):
            continue
        contract = record.get("verifier_contract") or UNKNOWN_CONTRACT
        key = (record["task"], record["model"], record["condition"], contract)
        trials[key].append(record.get("seed"))

    pairs = sorted({(task, model) for task, model, _, _ in trials})
    print("%-32s %-6s %-10s %-15s %-16s %s"
          % ("task", "model", "phase", "contract", "valid/required",
             "distinct seeds"))
    print("-" * 104)
    incomplete_pairs = []
    superseded_pairs = set()
    for task, model in pairs:
        for contract in sorted(
                {key[3] for key in trials
                 if key[:3] == (task, model, "smoke_baseline")},
                key=contract_order, reverse=True):
            smoke = trials[(task, model, "smoke_baseline", contract)]
            print("%-32s %-6s %-10s %-15s %-16s %d"
                  % (task, model, "S (screen)", contract,
                     "%d/1" % len(smoke), len(set(smoke))))
        has_smoke = any(key[:3] == (task, model, "smoke_baseline")
                        for key in trials)
        has_baseline = any(key[:3] == (task, model, "baseline")
                           for key in trials)

        complete = True
        for phase, condition, need_trials, need_seeds in REQUIRED:
            contracts = sorted(
                {key[3] for key in trials if key[:3] == (task, model, condition)},
                key=contract_order, reverse=True)
            if not contracts:
                complete = False
                print("%-32s %-6s %-10s %-15s %-16s %d%s"
                      % (task, model, phase, "-", "0/%d" % need_trials, 0,
                         "   <- incomplete"))
                continue
            current, older = contracts[0], contracts[1:]
            seen = trials[(task, model, condition, current)]
            seeds = len(set(seed for seed in seen if seed is not None))
            ok = len(seen) >= need_trials and seeds >= need_seeds
            complete = complete and ok
            print("%-32s %-6s %-10s %-15s %-16s %d%s"
                  % (task, model, phase, current,
                     "%d/%d" % (len(seen), need_trials), seeds,
                     "" if ok else "   <- incomplete"))
            if older:
                superseded_pairs.add((task, model))
            for contract in older:
                seen = trials[(task, model, condition, contract)]
                if not args.all_contracts:
                    continue
                print("%-32s %-6s %-10s %-15s %-16s %d   <- superseded"
                      % (task, model, phase, contract,
                         "%d" % len(seen),
                         len(set(s for s in seen if s is not None))))
        if not complete:
            incomplete_pairs.append((task, model, has_smoke, has_baseline))

    print()
    print("Cohorts without a complete retention record: %d of %d"
          % (len(incomplete_pairs), len(pairs)))
    screened_no_baseline = [
        entry for entry in incomplete_pairs if entry[2] and not entry[3]
    ]
    if screened_no_baseline:
        print("Of those, screened but never progressed to Phase A: %d"
              % len(screened_no_baseline))
        print("A phase-S verdict is one trial on one seed. Under SPEC section 9 a")
        print("candidate is retained only at no more than one pass in five distinct")
        print("seeds, so a single 'Pass' neither retains nor rejects a task on its own.")
    if superseded_pairs:
        print()
        print("Cohorts re-run under a newer contract: %d" % len(superseded_pairs))
        for task, model in sorted(superseded_pairs):
            print("  %s / %s" % (task, model))
        print("Only the newest contract is counted above. SPEC section 9 forbids")
        print("pooling contract versions, so earlier trials are neither added to the")
        print("counts nor deleted. Re-run with --all-contracts to list them.")
    print()
    print("Coverage is per model. A candidate that fails baseline for one model needs")
    print("the all-hint control for that model only, so the opposite model's phase C")
    print("is expected to read incomplete. See SPEC section 9.0 for the per-model gate")
    print("and how it differs from retention.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
