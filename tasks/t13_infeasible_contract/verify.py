#!/usr/bin/env python3
"""
T13 verifier.

The specification in the workspace is jointly unsatisfiable. A run passes only
when the submission (a) reports the infeasibility, (b) names the minimal
conflicting requirement pair recorded in ground truth, (c) drops exactly one of
the two requirements in that pair, and (d) implements the degraded mode that
corresponds to the requirement it dropped.

Prose in the proof section is checked for presence and substance only. The
verifier deliberately does not score the wording of the argument: the normative
claims scored here are the conflicting pair, the relaxation, and the observable
behaviour of the implementation.

Usage:
  python3 verify.py --workspace ./workspace --gt ./ground_truth.json \
      --hidden ./hidden_tests.py
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


RUNNER = r'''import importlib.util
import sys
import traceback

spec = importlib.util.spec_from_file_location("generated_hidden_tests", sys.argv[1])
module = importlib.util.module_from_spec(spec)
failures = []
tests_run = 0
try:
    spec.loader.exec_module(module)
    for name, value in sorted(vars(module).items()):
        if name.startswith("test_") and callable(value):
            tests_run += 1
            try:
                value()
            except BaseException:
                failures.append("%s\n%s" % (name, traceback.format_exc()))
except BaseException:
    failures.append("IMPORT\n%s" % traceback.format_exc())
print("%d tests, %d failures" % (tests_run, len(failures)))
if failures:
    print("\n".join(failures))
raise SystemExit(0 if tests_run and not failures else 1)
'''

CONFLICT_RE = re.compile(
    r"^[ \t>*-]*CONFLICT:\s*R\s*(\d+)\s*(?:\+|,|&|and)\s*R\s*(\d+)\s*[.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
RELAX_RE = re.compile(
    r"^[ \t>*-]*RELAX:\s*R\s*(\d+)\s*[.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PROOF_RE = re.compile(
    r"^#{1,6}\s*Proof\b[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
MIN_PROOF_CHARS = 120


def read_report(workspace):
    """Parse INFEASIBLE.md into its three normative fields."""
    path = os.path.join(workspace, "INFEASIBLE.md")
    report = {
        "present": os.path.isfile(path),
        "conflict_pair": None,
        "relax": None,
        "proof_chars": 0,
    }
    if not report["present"]:
        return report
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()

    conflicts = CONFLICT_RE.findall(text)
    if len(conflicts) == 1:
        report["conflict_pair"] = sorted(int(value) for value in conflicts[0])
    relaxations = RELAX_RE.findall(text)
    if len(relaxations) == 1:
        report["relax"] = int(relaxations[0])
    proof = PROOF_RE.search(text)
    if proof:
        report["proof_chars"] = len(" ".join(proof.group(1).split()))
    return report


def run_suites(workspace, hidden_path, branch):
    with tempfile.TemporaryDirectory() as tmp:
        staged = os.path.join(tmp, "workspace")
        shutil.copytree(workspace, staged)
        hidden_target = os.path.join(staged, "tests", "test_hidden.py")
        shutil.copy(hidden_path, hidden_target)
        env = dict(os.environ)
        env["T13_BRANCH"] = branch or ""
        visible = subprocess.run(
            [sys.executable, "tests/run_visible.py"], cwd=staged,
            capture_output=True, text=True, timeout=60,
        )
        hidden = subprocess.run(
            [sys.executable, "-c", RUNNER, hidden_target], cwd=staged,
            capture_output=True, text=True, timeout=120, env=env,
        )
    return visible, hidden


def classify_hidden(log):
    if "test_00_protected" in log:
        return "PROTECTED_FILE_MODIFIED"
    if "test_50_striped" in log or "test_60_coordinated" in log:
        return "miss_f3_mode_inconsistent_with_declared_relaxation"
    if "test_70_second_tenant" in log:
        return "miss_f3_mode_not_applied_per_tenant"
    if ("test_10_ticket" in log or "test_20_durability" in log or
            "test_30_per_replica" in log or "test_40_tenant" in log):
        return "miss_f3_retained_requirement_violated"
    return "OTHER_WRONG"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--gt", required=True)
    parser.add_argument("--hidden", required=True)
    args = parser.parse_args()

    with open(args.gt, encoding="utf-8") as handle:
        truth = json.load(handle)
    relax_options = {int(key): value for key, value in
                     truth["relax_options"].items()}

    report = read_report(args.workspace)
    branch = relax_options.get(report["relax"])
    visible, hidden = run_suites(args.workspace, args.hidden, branch)
    log = (hidden.stdout + "\n" + hidden.stderr)[-7000:]

    result = {
        "pass": False,
        "well_formed": visible.returncode == 0,
        "submitted": "repository_patch" if visible.returncode == 0 else None,
        "visible_pass": visible.returncode == 0,
        "hidden_pass": hidden.returncode == 0,
        "report_present": report["present"],
        "expected_conflict_pair": truth["conflict_pair"],
        "reported_conflict_pair": report["conflict_pair"],
        "reported_relaxation": report["relax"],
        "valid_relaxations": sorted(relax_options),
        "decoy_relaxation": truth["decoy_relaxation"],
        "resolved_mode": branch,
        "proof_chars": report["proof_chars"],
        "attribution": None,
        "hidden_log": log,
    }

    if visible.returncode != 0:
        result["attribution"] = "VISIBLE_REGRESSION"
    elif not report["present"]:
        result["attribution"] = "miss_f1_no_infeasibility_report"
    elif report["conflict_pair"] is None or report["relax"] is None:
        result["attribution"] = "miss_f1_malformed_infeasibility_report"
    elif report["proof_chars"] < MIN_PROOF_CHARS:
        result["attribution"] = "miss_f1_unsupported_infeasibility_claim"
    elif report["conflict_pair"] != truth["conflict_pair"]:
        result["attribution"] = "miss_f2_wrong_conflict_pair"
    elif report["relax"] not in relax_options:
        result["attribution"] = (
            "miss_f2_decoy_relaxation"
            if report["relax"] == truth["decoy_relaxation"]
            else "miss_f2_relaxation_outside_conflict")
    elif hidden.returncode != 0:
        result["attribution"] = classify_hidden(log)
    else:
        result["attribution"] = "CORRECT"

    result["pass"] = result["attribution"] == "CORRECT"
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
