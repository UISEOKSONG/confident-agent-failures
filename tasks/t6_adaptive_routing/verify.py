#!/usr/bin/env python3
"""Verify the adaptive router against every generated finite-world state."""
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
        "root_policy_correct": False, "metrics_exact": False,
        "adaptive_states_correct": False, "attribution": None,
    }
    for name, expected_hash in gt["protected_sha256"].items():
        path = os.path.join(args.workspace, name)
        if not os.path.isfile(path):
            result["inputs_unchanged"] = False
            continue
        with open(path, "rb") as handle:
            if hashlib.sha256(handle.read()).hexdigest() != expected_hash:
                result["inputs_unchanged"] = False
    required = ["router.py", "root_policy.json", "metrics.json"]
    missing = [name for name in required if not os.path.isfile(os.path.join(args.workspace, name))]
    if missing:
        result["attribution"] = "NO_OUTPUT:" + ",".join(missing)
        print(json.dumps(result, indent=2))
        return 1
    try:
        root_policy = read_json(os.path.join(args.workspace, "root_policy.json"))
        metrics = read_json(os.path.join(args.workspace, "metrics.json"))
    except (OSError, json.JSONDecodeError) as exc:
        result["attribution"] = "MALFORMED_OUTPUT"
        result["error"] = str(exc)
        print(json.dumps(result, indent=2))
        return 1
    result["submitted"] = root_policy
    result["root_policy_correct"] = root_policy == gt["root_policy"]
    result["metrics_exact"] = metrics == gt["metrics"]

    requests = {
        request["id"]: request
        for request in read_json(os.path.join(args.workspace, "routes.json"))["routes"]
    }
    gt_was_present = os.path.isfile(args.gt)
    if gt_was_present:
        os.remove(args.gt)
    try:
        spec = importlib.util.spec_from_file_location(
            "submitted_adaptive_router", os.path.join(args.workspace, "router.py")
        )
        module = importlib.util.module_from_spec(spec)
        old_cwd = os.getcwd()
        os.chdir(args.workspace)
        try:
            spec.loader.exec_module(module)
            correct = True
            checked = 0
            for state in gt["actions"]:
                attempts = [
                    {"plugin_id": plugin_id, "outcome": "failure"}
                    for plugin_id in state["failed"]
                ]
                actual = module.choose_next(
                    dict(requests[state["route_id"]]), attempts,
                    state["remaining_budget"],
                )
                checked += 1
                if actual != state["action"]:
                    correct = False
                    result["first_state_mismatch"] = {
                        "state": state, "actual": actual,
                    }
                    break
            if correct:
                sample_request = dict(next(iter(requests.values())))
                success_attempt = [{"plugin_id": "anything", "outcome": "success"}]
                correct = module.choose_next(sample_request, success_attempt, 22) is None
            result["adaptive_states_correct"] = correct
            result["states_checked"] = checked
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
    elif not result["root_policy_correct"]:
        result["attribution"] = "WRONG_ROOT_POLICY"
    elif not result["metrics_exact"]:
        result["attribution"] = "WRONG_METRICS"
    elif not result["adaptive_states_correct"]:
        result["attribution"] = "WRONG_ADAPTIVE_POLICY"
    else:
        result["attribution"] = "CORRECT"
        result["pass"] = True
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
