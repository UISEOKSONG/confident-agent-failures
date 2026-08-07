import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(task_id, seed, parent):
    task_dir = TASKS / task_id
    workspace = parent / "workspace"
    proc = subprocess.run(
        [
            sys.executable,
            str(task_dir / "gen_env.py"),
            "--seed",
            str(seed),
            "--out",
            str(workspace),
        ],
        cwd=task_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"generator for {task_id} failed ({proc.returncode}): {proc.stderr}"
        )
    return workspace, json.loads((parent / "ground_truth.json").read_text())


def tree_fingerprint(root):
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_verifier(task_id, *args):
    task_dir = TASKS / task_id
    proc = subprocess.run(
        [sys.executable, str(task_dir / "verify.py"), *map(str, args)],
        cwd=task_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        verdict = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"verifier for {task_id} did not emit JSON: {proc.stdout!r}; "
            f"stderr={proc.stderr!r}"
        ) from exc
    return proc, verdict
