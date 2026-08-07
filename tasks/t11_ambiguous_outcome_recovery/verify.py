#!/usr/bin/env python3
"""Run visible and hidden deterministic ambiguous-outcome checks."""
import argparse
import json
import os
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--hidden", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        workspace = os.path.join(tmp, "workspace")
        shutil.copytree(args.workspace, workspace)
        hidden_path = os.path.join(workspace, "tests", "test_hidden.py")
        shutil.copy(args.hidden, hidden_path)
        visible = subprocess.run(
            [sys.executable, "tests/run_visible.py"], cwd=workspace,
            capture_output=True, text=True, timeout=30,
        )
        hidden = subprocess.run(
            [sys.executable, "-c", RUNNER, hidden_path], cwd=workspace,
            capture_output=True, text=True, timeout=60,
        )
    log = (hidden.stdout + "\n" + hidden.stderr)[-7000:]
    if visible.returncode != 0:
        attribution = "VISIBLE_REGRESSION"
    elif hidden.returncode == 0:
        attribution = "CORRECT"
    elif "test_10_commit" in log:
        attribution = "miss_a1_ambiguous_timeout_reconciliation"
    elif "test_20_definite" in log:
        attribution = "miss_a3_fallback_scope"
    elif "test_30_cancellation" in log or "test_40_unknown" in log:
        attribution = "miss_a2_durable_recovery"
    elif "test_50_duplicate" in log:
        attribution = "miss_a3_stable_idempotency"
    else:
        attribution = "OTHER_WRONG"
    result = {
        "pass": visible.returncode == 0 and hidden.returncode == 0,
        "well_formed": visible.returncode == 0,
        "visible_pass": visible.returncode == 0,
        "hidden_pass": hidden.returncode == 0,
        "submitted": "repository_patch" if visible.returncode == 0 else None,
        "attribution": attribution,
        "hidden_log": log,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
