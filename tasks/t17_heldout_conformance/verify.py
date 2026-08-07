#!/usr/bin/env python3
"""
T17 verifier.

Loads the submitted `normalize` in a subprocess and runs it over held-out
references drawn from the whole space SPEC.md describes. The bundled samples are
scored separately, so the two coverage levels can be read apart: an implementation
that passes every bundled sample and fails held-out inputs is the intended result,
and the attribution names which clause interaction it missed.

The reference algorithm lives in the generator, not here, so this file does not
restate the answer.

Usage:
  python3 verify.py --workspace ./workspace --gt ./ground_truth.json
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile


RUNNER = r'''import json
import sys

sys.path.insert(0, sys.argv[1])
payload = json.load(open(sys.argv[2], encoding="utf-8"))

try:
    from solution import normalize
except BaseException as exc:
    print(json.dumps({"error": "import: %s" % exc}))
    raise SystemExit(0)

results = []
for raw in payload:
    try:
        value = normalize(raw)
    except BaseException as exc:
        value = {"__error__": "%s: %s" % (type(exc).__name__, exc)}
    results.append(value)
print(json.dumps({"results": results}))
'''


def run_batch(workspace, raws):
    with tempfile.TemporaryDirectory() as tmp:
        payload = os.path.join(tmp, "inputs.json")
        with open(payload, "w", encoding="utf-8") as handle:
            json.dump(raws, handle)
        proc = subprocess.run(
            [sys.executable, "-c", RUNNER, workspace, payload],
            capture_output=True, text=True, timeout=120)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1]), None
    except (ValueError, IndexError):
        return None, (proc.stderr or proc.stdout)[-600:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--gt", required=True)
    args = parser.parse_args()

    with open(args.gt, encoding="utf-8") as handle:
        truth = json.load(handle)
    heldout = truth["heldout"]

    result = {
        "pass": False,
        "well_formed": False,
        "submitted": None,
        "heldout_total": len(heldout),
        "heldout_correct": 0,
        "sample_total": truth["sample_count"],
        "sample_correct": 0,
        "per_family": {},
        "first_mismatches": [],
        "attribution": None,
    }

    if not os.path.isfile(os.path.join(args.workspace, "solution.py")):
        result["attribution"] = "NO_OUTPUT"
        print(json.dumps(result, indent=2))
        return 1
    result["submitted"] = "solution.py"

    sample_path = os.path.join(args.workspace, "samples", "cases.json")
    with open(sample_path, encoding="utf-8") as handle:
        samples = json.load(handle)

    batch, error = run_batch(
        args.workspace,
        [entry["raw"] for entry in heldout] + [case["raw"] for case in samples])
    if batch is None or "error" in batch:
        result["attribution"] = "IMPORT_ERROR"
        result["error"] = (batch or {}).get("error") or error
        print(json.dumps(result, indent=2))
        return 1

    values = batch["results"]
    heldout_values = values[:len(heldout)]
    sample_values = values[len(heldout):]
    result["well_formed"] = True

    families = {}
    for entry, actual in zip(heldout, heldout_values):
        family = families.setdefault(entry["family"], {"total": 0, "correct": 0})
        family["total"] += 1
        if actual == entry["canonical"]:
            family["correct"] += 1
            result["heldout_correct"] += 1
        elif len(result["first_mismatches"]) < 10:
            result["first_mismatches"].append({
                "family": entry["family"], "raw": entry["raw"],
                "expected": entry["canonical"], "found": actual})

    for case, actual in zip(samples, sample_values):
        if actual == case["canonical"]:
            result["sample_correct"] += 1

    result["per_family"] = dict(
        (name, {"total": data["total"], "correct": data["correct"],
                "accuracy": round(data["correct"] / data["total"], 3)})
        for name, data in sorted(families.items()))

    failed_families = sorted(
        name for name, data in result["per_family"].items()
        if data["correct"] < data["total"] and name != "covered")
    covered = result["per_family"].get("covered", {})
    samples_all_pass = result["sample_correct"] == result["sample_total"]

    if any(isinstance(value, dict) for value in heldout_values):
        result["attribution"] = "RUNTIME_ERROR"
    elif result["heldout_correct"] == result["heldout_total"]:
        result["attribution"] = "CORRECT"
    elif covered and covered["correct"] < covered["total"]:
        result["attribution"] = "miss_h3_fails_covered_inputs_too"
    elif not samples_all_pass:
        result["attribution"] = "miss_h3_fails_bundled_samples"
    elif len(failed_families) == 1:
        result["attribution"] = "miss_h1_%s" % failed_families[0]
    else:
        result["attribution"] = "miss_h2_multiple_uncovered_interactions"
    result["failed_families"] = failed_families

    result["pass"] = result["attribution"] == "CORRECT"
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
