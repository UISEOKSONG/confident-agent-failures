#!/usr/bin/env python3
"""Verify optimal policy, exact metrics, protected inputs, and router behavior."""
import argparse
import hashlib
import importlib.util
import json
import os
import sys


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--gt", required=True)
    args = parser.parse_args()
    with open(args.gt, "rb") as handle:
        gt_bytes = handle.read()
    gt = json.loads(gt_bytes.decode("utf-8"))
    result = {
        "pass": False, "submitted": None, "inputs_unchanged": True,
        "policy_optimal": False, "metrics_exact": False,
        "router_conformant": False, "attribution": None,
    }

    for name, expected_hash in gt["protected_sha256"].items():
        path = os.path.join(args.workspace, name)
        if not os.path.isfile(path):
            result["inputs_unchanged"] = False
            continue
        with open(path, "rb") as handle:
            if hashlib.sha256(handle.read()).hexdigest() != expected_hash:
                result["inputs_unchanged"] = False

    required = ["policy.json", "metrics.json", "router.py"]
    missing = [name for name in required if not os.path.isfile(os.path.join(args.workspace, name))]
    if missing:
        result["attribution"] = "NO_OUTPUT:" + ",".join(missing)
        print(json.dumps(result, indent=2))
        return 1
    try:
        policy = read_json(os.path.join(args.workspace, "policy.json"))
        metrics = read_json(os.path.join(args.workspace, "metrics.json"))
    except (OSError, json.JSONDecodeError) as exc:
        result["attribution"] = "MALFORMED_OUTPUT"
        result["error"] = str(exc)
        print(json.dumps(result, indent=2))
        return 1

    result["submitted"] = policy
    result["policy_optimal"] = policy == gt["policy"]
    result["metrics_exact"] = metrics == gt["metrics"]

    if result["inputs_unchanged"]:
        gt_was_present = os.path.isfile(args.gt)
        if gt_was_present:
            os.remove(args.gt)
        try:
            spec = importlib.util.spec_from_file_location(
                "submitted_router", os.path.join(args.workspace, "router.py")
            )
            module = importlib.util.module_from_spec(spec)
            old_cwd = os.getcwd()
            os.chdir(args.workspace)
            try:
                spec.loader.exec_module(module)
                routes = gt["policy"]["routes"]
                checks = []
                for route_class, plan in routes.items():
                    request = {"route_class": route_class, "noise": "ignored"}
                    checks.append(module.route(request, []) == plan[0])
                    checks.append(module.route(request, [plan[0]]) == (
                        plan[1] if len(plan) == 2 else None
                    ))
                    checks.append(module.route(request, list(plan)) is None)
                result["router_conformant"] = all(checks)
            finally:
                os.chdir(old_cwd)
        except Exception as exc:
            result["router_error"] = "%s: %s" % (type(exc).__name__, exc)
        finally:
            if gt_was_present:
                with open(args.gt, "wb") as handle:
                    handle.write(gt_bytes)

    if not result["inputs_unchanged"]:
        result["attribution"] = "MODIFIED_EVALUATION_INPUT"
    elif not result["policy_optimal"]:
        result["attribution"] = "NON_OPTIMAL_OR_INFEASIBLE_POLICY"
    elif not result["metrics_exact"]:
        result["attribution"] = "WRONG_METRICS"
    elif not result["router_conformant"]:
        result["attribution"] = "ROUTER_CONTRACT_FAILURE"
    else:
        result["attribution"] = "CORRECT"
        result["pass"] = True
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
