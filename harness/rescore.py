#!/usr/bin/env python3
"""Re-score every stored baseline cohort under the current verifiers.

SPEC section 9.2 allows a baseline to be carried forward across a verifier
correction when the correction cannot reach an unhinted cohort. That is a claim about
the corrections, and a claim is worth less than a measurement. This script makes the
measurement: it replays each stored run's workspace, response, and transcript through
the verifier as it exists today, and reports where the current contract disagrees with
the verdict recorded at the time.

The comparison is meaningful because scoring is deterministic and the runs directory
keeps the full workspace, the extracted response, the transcript, and the private
ground truth for every trial. No model is invoked and nothing is rewritten.

A cohort printed without CHANGED is one whose reported figure does not depend on the
contract it was originally scored under. A cohort printed with CHANGED needs its
figure read against the contract named in the output, and `docs/report.md` should say
so; T19's Fable cohort is the known and documented case.

Usage:
    python3 harness/rescore.py                 # reported candidates, baseline only
    python3 harness/rescore.py --all-tasks     # every task in runs/
    python3 harness/rescore.py --condition hint_all
"""
import argparse
import collections
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run as harness  # noqa: E402


REPORTED = (
    "t2_scoped_retrieval",
    "t14_uniform_insufficiency",
    "t18_unstated_domain_constraint",
    "t21_decoupled_axes",
    "t19_scoped_gaps",
)


def rescore_one(record, run_dir):
    """Return the current verifier's pass verdict for one stored run, or None."""
    workspace = os.path.join(run_dir, "workspace")
    ground_truth = os.path.join(run_dir, "ground_truth.json")
    if not os.path.isdir(workspace) or not os.path.isfile(ground_truth):
        return None
    task_dir, task = harness.load_task(record["task"])
    command = harness.verifier_command(
        record["task"], task_dir, task, workspace,
        {"ground_truth": ground_truth},
        os.path.join(run_dir, "response.txt"),
        os.path.join(run_dir, "transcript.txt"),
        record["condition"],
    )
    proc = subprocess.run(command, capture_output=True, text=True)
    try:
        return bool(json.loads(proc.stdout).get("pass"))
    except (ValueError, AttributeError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runs",
        default=os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "runs"),
    )
    parser.add_argument("--condition", default="baseline")
    parser.add_argument("--all-tasks", action="store_true")
    args = parser.parse_args()

    cohorts = collections.defaultdict(
        lambda: {"n": 0, "stored": 0, "now": 0, "skipped": 0, "moved": []})

    for dirpath, _, files in os.walk(args.runs):
        if "result.json" not in files:
            continue
        with open(os.path.join(dirpath, "result.json"), encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("excluded"):
            continue
        if record["condition"] != args.condition:
            continue
        if not args.all_tasks and record["task"] not in REPORTED:
            continue

        key = (record["task"], record["model"], record.get("verifier_contract"))
        cohort = cohorts[key]
        now = rescore_one(record, dirpath)
        if now is None:
            cohort["skipped"] += 1
            continue
        cohort["n"] += 1
        cohort["stored"] += 1 if record.get("pass") else 0
        cohort["now"] += 1 if now else 0
        if bool(record.get("pass")) != now:
            cohort["moved"].append(
                {"seed": record.get("seed"),
                 "stored": bool(record.get("pass")),
                 "rescored": now})

    if not cohorts:
        print("no %s runs found under %s" % (args.condition, args.runs))
        return 0

    print("condition: %s" % args.condition)
    print("%-32s %-6s %-15s %5s %8s %9s %s"
          % ("task", "model", "stored contract", "n", "stored", "rescored", ""))
    print("-" * 96)
    changed = []
    for key in sorted(cohorts, key=lambda k: tuple(str(part) for part in k)):
        task, model, contract = key
        cohort = cohorts[key]
        flag = "" if cohort["stored"] == cohort["now"] else "  <-- CHANGED"
        if flag:
            changed.append((key, cohort))
        note = flag
        if cohort["skipped"]:
            note += "  (%d run(s) lacked a stored workspace)" % cohort["skipped"]
        print("%-32s %-6s %-15s %5d %8d %9d%s"
              % (task, model, contract, cohort["n"], cohort["stored"],
                 cohort["now"], note))

    print()
    if not changed:
        print("Every cohort scores the same under the current verifiers as under the")
        print("contract it was recorded on. No reported figure depends on the")
        print("carry-forward allowed by SPEC section 9.2.")
        return 0

    print("Cohorts whose verdict count moved under the current verifiers: %d"
          % len(changed))
    for (task, model, contract), cohort in changed:
        print("  %s / %s (recorded on %s): %d/%d stored, %d/%d rescored"
              % (task, model, contract, cohort["stored"], cohort["n"],
                 cohort["now"], cohort["n"]))
        for move in cohort["moved"]:
            print("    seed %s: stored pass=%s, rescored pass=%s"
                  % (move["seed"], move["stored"], move["rescored"]))
    print()
    print("A moved cohort is not automatically wrong; it means the figure must be read")
    print("against a named contract. docs/report.md section 6 does this for T19.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
