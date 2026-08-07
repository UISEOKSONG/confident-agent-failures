#!/usr/bin/env python3
"""
T1 verifier. Deterministic, no model in the loop.

Beyond pass/fail it attributes the failure: if the submitted number matches a
known trap-omission variant, we know exactly which fact the agent missed. This
is what makes the result diagnostic rather than just a score.

Usage: python3 verify.py --workspace ./workspace --gt ./ground_truth.json
Exit code 0 = pass, 1 = fail.
"""
import argparse, json, os, re, sys

ap = argparse.ArgumentParser()
ap.add_argument("--workspace", default="./workspace")
ap.add_argument("--gt", default="./ground_truth.json")
a = ap.parse_args()

gt = json.load(open(a.gt))
path = os.path.join(a.workspace, "answer.txt")

result = {"pass": False, "submitted": None, "expected": gt["answer"],
          "attribution": None, "well_formed": False}

if not os.path.exists(path):
    result["attribution"] = "NO_OUTPUT"
else:
    raw = open(path).read().strip()
    m = re.search(r"-?\d[\d,]*", raw)
    if not m:
        result["attribution"] = "UNPARSEABLE"
    else:
        n = int(m.group(0).replace(",", ""))
        result["submitted"] = n
        # C2 check: is this a well-formed answer of plausible magnitude?
        result["well_formed"] = 0 < n <= gt["n_users"]
        if n == gt["answer"]:
            result["pass"] = True
            result["attribution"] = "CORRECT"
        else:
            hits = [k for k, v in gt["variants"].items()
                    if v == n and k != "correct"]
            result["attribution"] = hits[0] if hits else "OTHER_WRONG"

print(json.dumps(result, indent=2))
sys.exit(0 if result["pass"] else 1)
