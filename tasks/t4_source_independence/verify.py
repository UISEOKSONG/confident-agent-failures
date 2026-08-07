#!/usr/bin/env python3
"""Verify evidence selection, answer correctness, and executable analysis."""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile


FIELDS = ["root_source_id", "document_id", "publisher", "period", "metric", "value"]


def load_csv(path):
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise ValueError("wrong evidence header")
        rows = list(reader)
    if any(set(row) != set(FIELDS) or any(row[field] == "" for field in FIELDS) for row in rows):
        raise ValueError("malformed evidence row")
    return rows


def run_analysis(workspace, counterfactual=None):
    with tempfile.TemporaryDirectory() as tmp:
        case = os.path.join(tmp, "case")
        shutil.copytree(workspace, case)
        for name in ("documents", "provenance.csv", "QUESTION.md", "EVIDENCE_POLICY.md"):
            path = os.path.join(case, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.exists(path):
                os.remove(path)
        answer_path = os.path.join(case, "answer.json")
        if os.path.exists(answer_path):
            os.remove(answer_path)
        if counterfactual is not None:
            with open(os.path.join(case, "evidence.csv"), "a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writerow(counterfactual)
        try:
            proc = subprocess.run(
                [sys.executable, "analysis.py"], cwd=case, capture_output=True,
                text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, None, str(exc)
        if proc.returncode != 0 or not os.path.isfile(answer_path):
            return False, None, (proc.stderr or proc.stdout)[-1000:]
        try:
            with open(answer_path, encoding="utf-8") as handle:
                return True, json.load(handle), ""
        except (OSError, json.JSONDecodeError) as exc:
            return False, None, str(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--gt", required=True)
    args = parser.parse_args()
    with open(args.gt, encoding="utf-8") as handle:
        gt = json.load(handle)

    result = {
        "pass": False, "submitted": None, "answer_correct": False,
        "evidence_correct": False, "analysis_reproduces": False,
        "counterfactual_reproduces": False, "attribution": None,
    }
    evidence_path = os.path.join(args.workspace, "evidence.csv")
    answer_path = os.path.join(args.workspace, "answer.json")
    code_path = os.path.join(args.workspace, "analysis.py")
    missing = [name for name, path in (
        ("evidence.csv", evidence_path), ("answer.json", answer_path),
        ("analysis.py", code_path)) if not os.path.isfile(path)]
    if missing:
        result["attribution"] = "NO_OUTPUT:" + ",".join(missing)
        print(json.dumps(result, indent=2))
        return 1

    try:
        rows = load_csv(evidence_path)
        with open(answer_path, encoding="utf-8") as handle:
            submitted = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result["attribution"] = "MALFORMED_OUTPUT"
        result["error"] = str(exc)
        print(json.dumps(result, indent=2))
        return 1

    result["submitted"] = submitted
    result["answer_correct"] = submitted == gt["answer"]
    result["evidence_correct"] = rows == gt["evidence"]
    ok, regenerated, error = run_analysis(args.workspace)
    result["analysis_reproduces"] = ok and regenerated == gt["answer"]
    if error:
        result["analysis_error"] = error

    synthetic = {
        "root_source_id": "root-counterfactual", "document_id": "doc-counterfactual",
        "publisher": "Counterfactual Audit", "period": gt["period"],
        "metric": gt["metric"], "value": str(gt["threshold"]),
    }
    cf_ok, cf_answer, cf_error = run_analysis(args.workspace, synthetic)
    expected_cf = {
        "verdict": "SUPPORTED" if len(gt["evidence"]) + 1 >= 2 else "INSUFFICIENT_EVIDENCE",
        "independent_source_count": len(gt["evidence"]) + 1,
    }
    result["counterfactual_reproduces"] = cf_ok and cf_answer == expected_cf
    if cf_error:
        result["counterfactual_error"] = cf_error

    if not result["evidence_correct"]:
        roots = [row.get("root_source_id") for row in rows]
        if len(roots) != len(set(roots)) or len(rows) == gt["variants"]["miss_p1_counts_derivatives"]:
            result["attribution"] = "miss_p1_counts_derivatives"
        elif len(rows) >= gt["variants"]["miss_p2_counts_ineligible_roots"]:
            result["attribution"] = "miss_p2_counts_ineligible_roots"
        else:
            result["attribution"] = "WRONG_EVIDENCE"
    elif not result["answer_correct"]:
        result["attribution"] = "WRONG_ANSWER"
    elif not result["analysis_reproduces"]:
        result["attribution"] = "ANALYSIS_NOT_REPRODUCIBLE"
    elif not result["counterfactual_reproduces"]:
        result["attribution"] = "ANALYSIS_HARDCODED"
    else:
        result["attribution"] = "CORRECT"
        result["pass"] = True

    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
