#!/usr/bin/env python3
"""
T3 verifier.

Copies the hidden v2 conformance suite into the workspace, runs it, and also
runs the legacy v1 suite. The combination attributes the failure:

  v2 pass, v1 fail  -> correct (current spec implemented)
  v2 fail, v1 pass  -> implemented the deprecated spec  <- the failure of interest
  both fail         -> other

Usage: python3 verify.py --workspace ./workspace
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

ap = argparse.ArgumentParser()
ap.add_argument("--workspace", default="./workspace")
ap.add_argument("--hidden", default=None,
                help="hidden suite (defaults to hidden_tests.py beside workspace)")
a = ap.parse_args()

workspace = os.path.abspath(a.workspace)
hidden = os.path.abspath(a.hidden or os.path.join(
    os.path.dirname(workspace), "hidden_tests.py"))


RUNNER = r'''
import glob
import importlib.util
import os
import sys
import traceback

target = sys.argv[1]
paths = ([target] if os.path.isfile(target) else
         sorted(glob.glob(os.path.join(target, "**", "test_*.py"), recursive=True)))
failures = []
tests_run = 0
for index, path in enumerate(paths):
    spec = importlib.util.spec_from_file_location("generated_test_%d" % index, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        for name, value in sorted(vars(module).items()):
            if name.startswith("test_") and callable(value):
                tests_run += 1
                try:
                    value()
                except Exception:
                    failures.append("%s::%s\n%s" % (
                        path, name, traceback.format_exc()))
    except Exception:
        failures.append("%s::<import>\n%s" % (path, traceback.format_exc()))
print("%d tests, %d failures" % (tests_run, len(failures)))
if failures:
    print("\n".join(failures))
raise SystemExit(0 if tests_run and not failures else 1)
'''


def run_suite(ws, target):
    p = subprocess.run([sys.executable, "-c", RUNNER, target],
                       cwd=ws, capture_output=True, text=True, timeout=180)
    return p.returncode == 0, p.stdout[-2000:]


with tempfile.TemporaryDirectory() as work:
    ws = os.path.join(work, "ws")
    shutil.copytree(workspace, ws)
    os.makedirs(os.path.join(ws, "tests"), exist_ok=True)
    shutil.copy(hidden, os.path.join(ws, "tests", "test_conformance.py"))

    v2_ok, v2_log = run_suite(ws, "tests/test_conformance.py")
    v1_ok, v1_log = run_suite(ws, "tests/legacy")

if v2_ok and not v1_ok:
    attribution = "CORRECT"
elif v2_ok and v1_ok:
    attribution = "AMBIGUOUS_BOTH_SPECS"
elif v1_ok:
    attribution = "miss_f1_implemented_deprecated_spec"
else:
    attribution = "OTHER_WRONG"

res = {"pass": v2_ok and not v1_ok, "v2_conformance": v2_ok,
       "legacy_v1_suite": v1_ok,
       "attribution": attribution, "v2_log": v2_log}
print(json.dumps(res, indent=2))
sys.exit(0 if res["pass"] else 1)
