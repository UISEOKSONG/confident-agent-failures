#!/usr/bin/env python3
"""Report how much of the SPEC section 9 protocol each task/model has actually run.

`run.py --report` prints INCOMPLETE for any cohort that has not met the retention
requirement, but it does not distinguish "screened once" from "nearly finished".
A screening pass (phase S, one trial, one seed) is not evidence about a task; the
retention decision needs phase A at five distinct seeds. This report makes the gap
explicit so a candidate is never rejected on a single observation.

Usage: python3 harness/coverage.py [--runs ./runs]
"""
import argparse
import collections
import json
import os
import sys


REQUIRED = (
    ("A", "baseline", 5, 5),
    ("C", "hint_all", 3, 3),
)


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
    args = parser.parse_args()

    records = load(args.runs)
    if not records:
        print("no runs found under %s" % args.runs)
        return 0

    trials = collections.defaultdict(list)
    for record in records:
        if record.get("excluded"):
            continue
        trials[(record["task"], record["model"], record["condition"])].append(
            record.get("seed"))

    pairs = sorted({(task, model) for task, model, _ in trials})
    print("%-32s %-6s %-10s %-16s %s"
          % ("task", "model", "phase", "valid/required", "distinct seeds"))
    print("-" * 92)
    screened_only = []
    for task, model in pairs:
        smoke = trials.get((task, model, "smoke_baseline"), [])
        if smoke:
            print("%-32s %-6s %-10s %-16s %d"
                  % (task, model, "S (screen)", "%d/1" % len(smoke),
                     len(set(smoke))))
        complete = True
        for phase, condition, need_trials, need_seeds in REQUIRED:
            seen = trials.get((task, model, condition), [])
            seeds = len(set(seed for seed in seen if seed is not None))
            ok = len(seen) >= need_trials and seeds >= need_seeds
            complete = complete and ok
            print("%-32s %-6s %-10s %-16s %d%s"
                  % (task, model, phase, "%d/%d" % (len(seen), need_trials),
                     seeds, "" if ok else "   <- incomplete"))
        if not complete:
            screened_only.append((task, model, bool(smoke)))

    print()
    print("Cohorts without a complete retention record: %d of %d"
          % (len(screened_only), len(pairs)))
    only_screened = [entry for entry in screened_only if entry[2]]
    if only_screened:
        print("Of those, decided on a single screening trial only: %d"
              % len(only_screened))
        print("A phase-S verdict is one trial on one seed. Under SPEC section 9 a")
        print("candidate is retained only at no more than one pass in five distinct")
        print("seeds, so a single 'Pass' neither retains nor rejects a task on its own.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
