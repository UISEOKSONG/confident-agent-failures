#!/usr/bin/env python3
"""Run generated grounding tasks and aggregate attributable model results."""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import uuid


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "runs")
VERIFIER_CONTRACT = "2026-08-04-v10"
# Offset 1 is rejected by T1 because a decoy answer collides with ground truth.
DEFAULT_SEED_OFFSETS = (0, 2, 3, 4, 5)
with open(os.path.join(ROOT, "harness", "models.json"), encoding="utf-8") as f:
    MODELS = json.load(f)
_CLI_VERSION_CACHE = {}


def cli_version(executable):
    if executable in _CLI_VERSION_CACHE:
        return _CLI_VERSION_CACHE[executable]
    try:
        output = subprocess.check_output(
            [executable, "--version"], text=True, stderr=subprocess.STDOUT,
            timeout=10,
        )
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        version = lines[-1] if lines else None
    except (OSError, subprocess.SubprocessError):
        version = None
    _CLI_VERSION_CACHE[executable] = version
    return version


def _indented_block(lines, start, parent_indent, folded=False):
    """Read the small YAML block-scalar subset used by task.yaml files."""
    block = []
    i = start
    while i < len(lines):
        line = lines[i]
        if line.strip() and len(line) - len(line.lstrip()) <= parent_indent:
            break
        block.append(line)
        i += 1
    nonempty = [len(line) - len(line.lstrip()) for line in block if line.strip()]
    indent = min(nonempty) if nonempty else parent_indent + 2
    text = "\n".join(line[indent:] if line.strip() else "" for line in block).strip()
    if folded:
        text = "\n\n".join(
            " ".join(part.split()) for part in re.split(r"\n\s*\n", text)
        )
    return text, i


def _load_task_metadata(path):
    """Load required task metadata without a third-party YAML dependency."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    task = {"traps": []}
    for i, line in enumerate(lines):
        seed = re.match(r"^seed:\s*(\d+)\s*$", line)
        verifier = re.match(r"^verifier:\s*([^#\s]+)", line)
        verifier_inputs = re.match(r"^verifier_inputs:\s*([a-z_, ]+)\s*$", line)
        retention_control = re.match(r"^retention_control:\s*([a-z_]+)\s*$", line)
        prompt = re.match(r"^prompt:\s*([|>])", line)
        if seed:
            task["seed"] = int(seed.group(1))
        elif verifier:
            task["verifier"] = verifier.group(1)
        elif verifier_inputs:
            task["verifier_inputs"] = [
                value.strip() for value in verifier_inputs.group(1).split(",")
                if value.strip()
            ]
        elif retention_control:
            task["retention_control"] = retention_control.group(1)
        elif prompt:
            task["prompt"], _ = _indented_block(
                lines, i + 1, 0, folded=prompt.group(1) == ">"
            )

    trap_starts = [
        i for i, line in enumerate(lines) if re.match(r"^\s{2}- id:\s*", line)
    ]
    for pos, start in enumerate(trap_starts):
        end = trap_starts[pos + 1] if pos + 1 < len(trap_starts) else len(lines)
        trap = {"id": lines[start].split(":", 1)[1].strip()}
        for i in range(start + 1, end):
            hint = re.match(r"^\s{4}hint:\s*([|>])", lines[i])
            if hint:
                trap["hint"], _ = _indented_block(
                    lines, i + 1, 4, folded=hint.group(1) == ">"
                )
                break
        if "hint" in trap:
            task["traps"].append(trap)

    missing = {"seed", "prompt", "verifier"} - task.keys()
    if missing:
        raise ValueError(f"unsupported task metadata in {path}: missing {sorted(missing)}")
    return task


def load_task(task_id):
    task_dir = os.path.join(ROOT, "tasks", task_id)
    return task_dir, _load_task_metadata(os.path.join(task_dir, "task.yaml"))


def make_workspace(task_dir, seed, run_id):
    """Generate a run and return its workspace plus private artifact paths."""
    run_dir = os.path.join(RUNS, run_id)
    ws = os.path.join(run_dir, "workspace")
    os.makedirs(run_dir, exist_ok=True)
    subprocess.run(
        [sys.executable, os.path.join(task_dir, "gen_env.py"),
         "--seed", str(seed), "--out", ws],
        check=True, capture_output=True, text=True, cwd=task_dir,
    )
    return ws, {
        "ground_truth": os.path.join(run_dir, "ground_truth.json"),
        "hidden_tests": os.path.join(run_dir, "hidden_tests.py"),
        "oracle_policy": os.path.join(run_dir, "oracle_policy.json"),
        "oracle_evidence": os.path.join(run_dir, "oracle_evidence.json"),
    }


def render_prompt(task, run_id, hints):
    prompt = task["prompt"]
    gt_path = os.path.join(RUNS, run_id, "ground_truth.json")
    if os.path.exists(gt_path):
        with open(gt_path, encoding="utf-8") as f:
            gt = json.load(f)
        if "{TOPIC}" in prompt:
            prompt = prompt.replace("{TOPIC}", gt["topic"])
        if "asker" in gt:
            principal = os.path.join(RUNS, run_id, "workspace", "PRINCIPAL.txt")
            with open(principal, "w", encoding="utf-8") as f:
                f.write(gt["asker"])
    if hints:
        prompt += "\n\n" + "\n".join(h.strip() for h in hints)
    return prompt


def conceal_private_artifacts(artifacts):
    """Remove verifier-only files while the agent runs, retaining exact bytes."""
    concealed = {}
    for name, path in artifacts.items():
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                concealed[name] = (path, handle.read())
            os.remove(path)
    return concealed


def restore_private_artifacts(concealed):
    for path, content in concealed.values():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)


def inject_oracle(prompt, condition, artifacts, workspace):
    """Inject oracle evidence into context without consuming retrieval budget."""
    kinds = []
    if condition in ("oracle_policy", "oracle_full"):
        kinds.append("oracle_policy")
    if condition in ("oracle_evidence", "oracle_full"):
        kinds.append("oracle_evidence")
    if not kinds:
        return prompt

    sections = []
    injected_ids = []
    for kind in kinds:
        path = artifacts.get(kind)
        if not path or not os.path.isfile(path):
            raise ValueError(f"missing private artifact for {condition}: {kind}")
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        for document in payload.get("documents", []):
            injected_ids.append(document["doc_id"])
            sections.append(
                "[ORACLE DOCUMENT: %s | %s]\n%s" % (
                    document["doc_id"], document["title"], document["body"]
                )
            )

    audit_path = os.path.join(workspace, "retrieval_audit.jsonl")
    event = {
        "seq": 0,
        "op": "injected",
        "oracle_condition": condition,
        "returned_doc_ids": injected_ids,
        "accepted": True,
        "budget_remaining": {"search": 8, "read": 12},
    }
    with open(audit_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return prompt + "\n\n# Oracle context (budget-free)\n\n" + "\n\n".join(sections)


def detect_model(transcript, expected_pattern):
    """Record the model identity reported by the runtime."""
    candidates = []

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = key.lower().replace("_", "").replace("-", "")
                if normalized in {"model", "modelname", "modelid"} and isinstance(child, str):
                    candidates.append(child)
                elif normalized == "modelusage" and isinstance(child, dict):
                    candidates.extend(str(name) for name in child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for line in transcript.splitlines():
        try:
            visit(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue

    candidates.extend(re.findall(
        r"\bmodel(?:_name|_id)?\b\s*[:=]\s*[\"]?([A-Za-z0-9._\-]+)",
        transcript,
        re.I,
    ))
    candidates = list(dict.fromkeys(candidates))
    reported = next(
        (name for name in candidates if re.search(expected_pattern, name, re.I)),
        candidates[0] if candidates else None,
    )
    return reported, bool(reported and re.search(expected_pattern, reported, re.I))


def extract_usage(transcript):
    """Pull token counts and billed cost from whichever CLI produced the log.

    Claude Code emits a terminal `result` object carrying `usage` and
    `total_cost_usd`; Codex emits `turn.completed` with its own `usage` shape.
    Both are read here so per-run cost is recorded in result.json rather than
    having to be reconstructed from transcripts afterwards.
    """
    usage = {}
    cost = None

    def visit(value):
        nonlocal cost
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, dict):
            return
        if value.get("type") in ("result", "turn.completed"):
            block = value.get("usage")
            if isinstance(block, dict):
                usage.update(
                    (key, block[key]) for key in block
                    if isinstance(block.get(key), (int, float))
                )
            if isinstance(value.get("total_cost_usd"), (int, float)):
                cost = value["total_cost_usd"]
        for child in value.values():
            if isinstance(child, (dict, list)):
                visit(child)

    for line in transcript.splitlines():
        try:
            visit(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue

    if not usage and cost is None:
        return None
    record = {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens",
                                             usage.get("cached_input_tokens")),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens",
                                                 usage.get("cache_write_input_tokens")),
        "reasoning_output_tokens": usage.get("reasoning_output_tokens"),
        "total_cost_usd": cost,
    }
    return dict((key, value) for key, value in record.items() if value is not None)


def detect_infrastructure_error(transcript):
    """Detect transport or session failures, not failures inside the agent's work.

    An earlier version matched a bare `"is_error": true` anywhere in the
    transcript. That flag also marks an ordinary failed tool call, so any run in
    which the agent's own command exited non-zero was excluded as infrastructure.
    Exclusions therefore concentrated on the runs where the agent struggled most,
    which is exactly the wrong direction for a failure study. The flag is now read
    only on a top-level session result.
    """
    patterns = (
        r"<TIMEOUT>",
        r"<RUNNER_ERROR:",
        r'"authentication_failed"',
        r'"terminal_reason"\s*:\s*"api_error"',
        r"\bNot logged in\b",
        r"failed to initialize in-process app-server client",
    )
    if any(re.search(pattern, transcript, re.IGNORECASE) for pattern in patterns):
        return True

    terminal = []

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, dict):
            return
        if value.get("type") == "result":
            terminal.append(
                bool(value.get("is_error")) or
                value.get("subtype") in {"error_during_execution", "error_max_turns"}
            )
        for child in value.values():
            if isinstance(child, (dict, list)):
                visit(child)

    for line in transcript.splitlines():
        try:
            visit(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue
    return any(terminal)


def extract_user_response(transcript):
    """Extract the final user-visible message from supported structured CLI logs."""
    values = []
    for line in transcript.splitlines():
        try:
            values.append(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue

    result_messages = []
    agent_messages = []

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, dict):
            return

        if value.get("type") == "result" and isinstance(value.get("result"), str):
            result_messages.append(value["result"])
        if value.get("type") == "item.completed":
            item = value.get("item", {})
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                agent_messages.append(item["text"])
        for child in value.values():
            if isinstance(child, (dict, list)):
                visit(child)

    for value in values:
        visit(value)
    if result_messages:
        return result_messages[-1]
    if agent_messages:
        return agent_messages[-1]
    return ""


def verifier_command(task_id, task_dir, task, ws, artifacts, response_path,
                     transcript_path, condition=None):
    """Build the verifier contract for a task without exposing private files."""
    cmd = [sys.executable, os.path.join(task_dir, task["verifier"]),
           "--workspace", ws]
    inputs = task.get("verifier_inputs", [])
    if "ground_truth" in inputs:
        cmd += ["--gt", artifacts["ground_truth"]]
    if "response" in inputs:
        cmd += ["--response", response_path]
    if "transcript" in inputs:
        cmd += ["--transcript", transcript_path]
    if "condition" in inputs:
        cmd += ["--condition", condition or "baseline"]
    if "hidden_tests" in inputs:
        cmd += ["--hidden", artifacts["hidden_tests"]]
    return cmd


def _silent_failure(verdict):
    if verdict.get("pass"):
        return False
    if verdict.get("abstained"):
        return False
    if "well_formed" in verdict:
        return bool(verdict["well_formed"])
    attribution = verdict.get("attribution")
    if attribution in (None, "NO_OUTPUT", "UNPARSEABLE", "VERIFIER_ERROR"):
        return False
    return verdict.get("submitted") not in (None, "") or attribution in {
        "miss_f1_implemented_deprecated_spec", "OTHER_WRONG"
    }


def one_run(task_id, model_key, condition, hints, trial, seed=None, attempt=1,
            experiment_id="adhoc"):
    task_dir, task = load_task(task_id)
    seed = task["seed"] if seed is None else seed
    run_id = (f"{experiment_id}/{task_id}/{model_key}/{condition}/"
              f"s{seed}-v{trial}-a{attempt}-{uuid.uuid4().hex[:6]}")
    ws, artifacts = make_workspace(task_dir, seed, run_id)
    prompt = render_prompt(task, run_id, hints)
    prompt = inject_oracle(prompt, condition, artifacts, ws)

    cfg = MODELS[model_key]
    cmd = [part.replace("{PROMPT}", prompt).replace("{WORKSPACE}", ws)
           for part in cfg["cmd"]]
    runtime_cli_version = cli_version(cmd[0])
    started = dt.datetime.now()
    returncode = None
    concealed = conceal_private_artifacts(artifacts)
    try:
        try:
            proc = subprocess.run(
                cmd, cwd=ws, capture_output=True, text=True,
                timeout=cfg.get("timeout_s", 1800),
            )
            transcript = proc.stdout + "\n" + proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            transcript = "<TIMEOUT>"
        except OSError as exc:
            transcript = f"<RUNNER_ERROR: {exc}>"
    finally:
        restore_private_artifacts(concealed)
    elapsed = (dt.datetime.now() - started).total_seconds()

    transcript_path = os.path.join(RUNS, run_id, "transcript.txt")
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript)
    response_path = os.path.join(RUNS, run_id, "response.txt")
    with open(response_path, "w", encoding="utf-8") as f:
        f.write(extract_user_response(transcript))

    verify = subprocess.run(
        verifier_command(
            task_id, task_dir, task, ws, artifacts, response_path,
            transcript_path, condition,
        ),
        capture_output=True, text=True, cwd=task_dir,
    )
    try:
        verdict = json.loads(verify.stdout)
    except json.JSONDecodeError:
        verdict = {
            "pass": False,
            "attribution": "VERIFIER_ERROR",
            "stderr": verify.stderr[-500:],
        }

    reported, identity_ok = detect_model(transcript, cfg["expect_model_pattern"])
    identity_source = "runtime" if identity_ok else None
    infrastructure_error = detect_infrastructure_error(transcript)
    if (not identity_ok and not infrastructure_error and returncode == 0 and
            cfg.get("identity_source") == "configured_cli"):
        reported = cfg["requested_model"]
        identity_ok = True
        identity_source = "configured_cli"
    refused = bool(re.search(
        r"\b(I can'?t help|I(?:'| a)m unable to|cannot assist|must refuse)\b",
        transcript, re.I,
    ))
    exclusion_reasons = []
    if not identity_ok:
        exclusion_reasons.append("model_identity")
    if refused:
        exclusion_reasons.append("refusal")
    if infrastructure_error:
        exclusion_reasons.append("infrastructure_error")
    excluded = bool(exclusion_reasons)

    record = {
        "run_id": run_id,
        "experiment_id": experiment_id,
        "task": task_id,
        "model": model_key,
        "condition": condition,
        "trial": trial,
        "scheduled_trial": trial,
        "valid_trial": None if excluded else trial,
        "attempt": attempt,
        "seed": seed,
        "excluded": excluded,
        "exclusion_reasons": exclusion_reasons,
        "pass": bool(verdict.get("pass", False)),
        "silent_failure": False if excluded else _silent_failure(verdict),
        "attribution": verdict.get("attribution"),
        "verdict": verdict,
        "elapsed_s": round(elapsed, 1),
        "agent_returncode": returncode,
        "verifier_returncode": verify.returncode,
        "verifier_contract": VERIFIER_CONTRACT,
        "reported_model": reported,
        "requested_model": cfg.get("requested_model"),
        "identity_source": identity_source,
        "cli_version": runtime_cli_version,
        "model_identity_ok": identity_ok,
        "infrastructure_error": infrastructure_error,
        "refused": refused,
        "usage": extract_usage(transcript),
        "ts": started.isoformat(),
    }
    with open(os.path.join(RUNS, run_id, "result.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    status = "EXCLUDED:" + "+".join(exclusion_reasons) if excluded else (
        "PASS" if record["pass"] else f"fail:{record['attribution']}"
    )
    print(f"  {model_key:8s} {condition:16s} s{seed} v{trial} a{attempt}  {status}")
    return record


def _run_trials(task_id, model_key, condition, hints, count, seeds, retry_cap,
                experiment_id):
    records = []
    for trial in range(1, count + 1):
        seed = seeds[(trial - 1) % len(seeds)]
        for attempt in range(1, retry_cap + 2):
            record = one_run(
                task_id, model_key, condition, hints, trial,
                seed=seed, attempt=attempt, experiment_id=experiment_id,
            )
            records.append(record)
            if not record["excluded"]:
                break
    return records


def phase(task_id, model_key, ph, seeds=None, retry_cap=None,
          experiment_id="adhoc"):
    _, task = load_task(task_id)
    seeds = list(seeds) if seeds else _default_seeds(task)
    if retry_cap is None:
        retry_cap = MODELS[model_key].get("max_excluded_retries", 2)
    if retry_cap < 0:
        raise ValueError("retry cap must be non-negative")

    if ph == "S":
        return _run_trials(
            task_id, model_key, "smoke_baseline", [], 1, seeds, retry_cap,
            experiment_id,
        )
    if ph == "R":
        records = []
        for condition in ("baseline", "oracle_policy", "oracle_evidence", "oracle_full"):
            records.extend(_run_trials(
                task_id, model_key, condition, [], 1, seeds, retry_cap,
                experiment_id,
            ))
        return records
    if ph == "A":
        return _run_trials(
            task_id, model_key, "baseline", [], 5, seeds, retry_cap,
            experiment_id,
        )
    if ph == "B":
        records = []
        for omitted in task["traps"]:
            hints = [trap["hint"] for trap in task["traps"]
                     if trap["id"] != omitted["id"]]
            records.extend(_run_trials(
                task_id, model_key, f"without_{omitted['id']}", hints,
                3, seeds, retry_cap, experiment_id,
            ))
        return records
    if ph == "C":
        hints = [trap["hint"] for trap in task["traps"]]
        return _run_trials(
            task_id, model_key, "hint_all", hints, 3, seeds, retry_cap,
            experiment_id,
        )
    if ph == "O":
        records = []
        for condition in ("oracle_policy", "oracle_evidence", "oracle_full"):
            records.extend(_run_trials(
                task_id, model_key, condition, [], 3, seeds, retry_cap,
                experiment_id,
            ))
        return records
    raise ValueError(f"unknown phase: {ph}")


def _excluded(record):
    return record.get("excluded", record.get("refused") or not record.get("model_identity_ok"))


def _rate(numerator, denominator):
    return "-" if not denominator else f"{100 * numerator / denominator:.1f}%"


def _retention(valid_records, task, model, experiment_id="legacy"):
    cohort = [
        r for r in valid_records
        if r["task"] == task and r["model"] == model and
        r.get("experiment_id", "legacy") == experiment_id
    ]
    baseline = [r for r in cohort if r["condition"] == "baseline"]
    try:
        _, task_metadata = load_task(task)
        control_condition = task_metadata.get("retention_control", "hint_all")
    except (OSError, ValueError):
        control_condition = "hint_all"
    full = [r for r in cohort if r["condition"] == control_condition]
    baseline_seeds = {r.get("seed") for r in baseline if r.get("seed") is not None}
    full_seeds = {r.get("seed") for r in full if r.get("seed") is not None}
    if len(baseline) != 5 or len(full) != 3:
        return "INCOMPLETE"
    if len(baseline_seeds) < 5 or len(full_seeds) < 3:
        return "INCOMPLETE"
    # v9: a task is retained at four or five baseline failures, not five only.
    # Five trials against a model whose true per-instance failure rate is 0.8 --
    # the rate Fable shows on T2 and T14 -- clear a strict 0/5 bar only 33% of
    # the time, so the old threshold rejected two thirds of genuinely failing
    # candidates. At four-of-five the same task is retained 74% of the time,
    # while a task the model mostly solves (failure rate 0.2) is retained 0.7%
    # of the time. See SPEC section 9.1.
    phase_a = sum(bool(r.get("pass", False)) for r in baseline) <= 1
    silent_baseline = sum(bool(
        r.get("silent_failure", _silent_failure(r.get("verdict", r)))
    ) for r in baseline)
    phase_a_silent = silent_baseline >= 3
    phase_c = sum(bool(r.get("pass", False)) for r in full) / len(full) >= 2 / 3
    return "RETAIN" if phase_a and phase_a_silent and phase_c else "DROP"


def _oracle_attribution(rows):
    """Derive retrieval attribution from paired oracle-condition cohorts."""
    by_condition = {}
    for row in rows:
        if not _excluded(row):
            by_condition.setdefault(row["condition"], []).append(row)
    required = ("baseline", "oracle_policy", "oracle_evidence", "oracle_full")
    if any(not by_condition.get(condition) for condition in required):
        return "INCOMPLETE"
    if any(row.get("seed") is None for condition in required
           for row in by_condition[condition]):
        return "INCOMPLETE"
    baseline_seeds = {row["seed"] for row in by_condition["baseline"]}
    oracle_seed_sets = [
        {row["seed"] for row in by_condition[condition]}
        for condition in required[1:]
    ]
    if not all(seeds == oracle_seed_sets[0] for seeds in oracle_seed_sets[1:]):
        return "INCOMPLETE"
    if not oracle_seed_sets[0].issubset(baseline_seeds):
        return "INCOMPLETE"
    baseline_failed = not any(row.get("pass") for row in by_condition["baseline"])
    if not baseline_failed:
        return "NO_BASELINE_FAILURE"

    def recovered(condition):
        cohort = by_condition[condition]
        return sum(bool(row.get("pass")) for row in cohort) / len(cohort) >= 2 / 3

    policy = recovered("oracle_policy")
    evidence = recovered("oracle_evidence")
    full = recovered("oracle_full")
    if not full:
        return "NO_FULL_ORACLE_RECOVERY"
    if policy and evidence:
        return "NONIDENTIFIABLE_SINGLE_ORACLE_RECOVERY"
    if policy:
        return "POLICY_RETRIEVAL_FAILURE"
    if evidence:
        return "EVIDENCE_RETRIEVAL_FAILURE"
    return "JOINT_RETRIEVAL_FAILURE"


def report():
    records = []
    stale_records = 0
    if os.path.isdir(RUNS):
        for dirpath, _, files in os.walk(RUNS):
            if "result.json" in files:
                with open(os.path.join(dirpath, "result.json"), encoding="utf-8") as f:
                    record = json.load(f)
                if record.get("verifier_contract") == VERIFIER_CONTRACT:
                    records.append(record)
                else:
                    stale_records += 1

    if stale_records:
        print(f"\nIgnored {stale_records} run(s) from an older verifier contract.")

    valid = [r for r in records if not _excluded(r)]
    groups = {}
    for record in records:
        key = (record.get("experiment_id", "legacy"), record["task"],
               record["model"], record["condition"])
        groups.setdefault(key, []).append(record)

    print("\nCondition results")
    print(f"{'experiment':18s} {'task':22s} {'model':8s} {'condition':16s} {'attempts':>8s} "
          f"{'valid':>5s} {'excl':>5s} {'seeds':>10s} {'pass':>7s} {'silent':>7s}")
    print("-" * 117)
    for (experiment_id, task, model, condition), rows in sorted(groups.items()):
        counted = [r for r in rows if not _excluded(r)]
        failures = [r for r in counted if not r.get("pass", False)]
        silent = sum(bool(r.get("silent_failure", _silent_failure(r.get("verdict", r))))
                     for r in failures)
        seeds = sorted({r.get("seed") for r in rows if r.get("seed") is not None})
        passes = sum(bool(r.get("pass", False)) for r in counted)
        print(f"{experiment_id[:18]:18s} {task:22s} {model:8s} {condition:16s} {len(rows):8d} "
              f"{len(counted):5d} {len(rows) - len(counted):5d} "
              f"{','.join(map(str, seeds)):>10s} {_rate(passes, len(counted)):>7s} "
              f"{_rate(silent, len(failures)):>7s}")

    print("\nExperiment/model aggregates")
    print(f"{'experiment':18s} {'model':8s} {'attempts':>8s} {'valid':>5s} "
          f"{'excl':>5s} {'pass':>7s} {'silent':>7s} {'retention':>12s}")
    print("-" * 81)
    experiment_models = sorted({
        (r.get("experiment_id", "legacy"), r["model"]) for r in records
    })
    for experiment_id, model in experiment_models:
        attempts = [
            r for r in records if r["model"] == model and
            r.get("experiment_id", "legacy") == experiment_id
        ]
        counted = [r for r in attempts if not _excluded(r)]
        failures = [r for r in counted if not r.get("pass", False)]
        silent = sum(bool(r.get("silent_failure", _silent_failure(r.get("verdict", r))))
                     for r in failures)
        retention = [
            _retention(valid, task, model, experiment_id)
            for task in sorted({r["task"] for r in attempts})
        ]
        retained = sum(status == "RETAIN" for status in retention)
        evaluated = sum(status != "INCOMPLETE" for status in retention)
        retention_text = f"{retained}/{evaluated}" if evaluated else "incomplete"
        passes = sum(bool(r.get("pass", False)) for r in counted)
        print(f"{experiment_id[:18]:18s} {model:8s} {len(attempts):8d} {len(counted):5d} "
              f"{len(attempts) - len(counted):5d} {_rate(passes, len(counted)):>7s} "
              f"{_rate(silent, len(failures)):>7s} {retention_text:>12s}")

    print("\nRetention by experiment/task/model")
    retention_keys = sorted({
        (r.get("experiment_id", "legacy"), r["task"], r["model"])
        for r in records
    })
    for experiment_id, task, model in retention_keys:
        print(f"  {experiment_id[:18]:18s} {task:22s} {model:8s} "
              f"{_retention(valid, task, model, experiment_id)}")

    oracle_keys = sorted({
        (r.get("experiment_id", "legacy"), r["task"], r["model"])
        for r in records if r["condition"].startswith("oracle_")
    })
    if oracle_keys:
        print("\nOracle attribution by experiment/task/model")
        for experiment_id, task, model in oracle_keys:
            cohort = [
                r for r in records
                if r.get("experiment_id", "legacy") == experiment_id and
                r["task"] == task and r["model"] == model
            ]
            print(f"  {experiment_id[:18]:18s} {task:22s} {model:8s} "
                  f"{_oracle_attribution(cohort)}")
    return records


def _parse_seeds(task_id, seed_args, seeds_arg):
    if seed_args and seeds_arg:
        raise ValueError("use either --seed or --seeds, not both")
    if seed_args:
        return seed_args
    if seeds_arg:
        seeds = [int(value.strip()) for value in seeds_arg.split(",") if value.strip()]
        if not seeds:
            raise ValueError("--seeds requires at least one integer")
        return seeds
    _, task = load_task(task_id)
    return _default_seeds(task)


def _default_seeds(task):
    return [task["seed"] + offset for offset in DEFAULT_SEED_OFFSETS]


def _new_experiment_id():
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task")
    parser.add_argument("--model", default="all")
    parser.add_argument(
        "--phase", default="A", choices=["S", "R", "A", "B", "C", "O", "all"],
        help="S is one baseline smoke; R screens baseline plus three oracles; O runs oracle controls",
    )
    parser.add_argument("--seed", action="append", type=int,
                        help="instance seed; repeat for deterministic round-robin scheduling")
    parser.add_argument("--seeds", help="comma-separated instance seeds")
    parser.add_argument("--retry-cap", type=int, default=None,
                        help="retries after an excluded identity/refusal attempt")
    parser.add_argument(
        "--experiment-id",
        help="cohort id shared by A/B/C; defaults to a new timestamped id",
    )
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        report()
        return 0
    if not args.task:
        parser.error("--task is required unless --report is used")
    if args.model != "all" and args.model not in MODELS:
        parser.error(f"unknown model: {args.model}")
    if args.retry_cap is not None and args.retry_cap < 0:
        parser.error("--retry-cap must be non-negative")
    experiment_id = args.experiment_id or _new_experiment_id()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", experiment_id):
        parser.error("--experiment-id must use 1-64 letters, numbers, dot, dash, or underscore")
    try:
        seeds = _parse_seeds(args.task, args.seed, args.seeds)
    except ValueError as exc:
        parser.error(str(exc))

    models = list(MODELS) if args.model == "all" else [args.model]
    phases = ["A", "B", "C", "O"] if args.phase == "all" else [args.phase]
    print(f"Experiment: {experiment_id}")
    for model in models:
        for ph in phases:
            label = " (leave-one-trap-out)" if ph == "B" else ""
            print(f"\n== {args.task} / {model} / phase {ph}{label} ==")
            phase(
                args.task, model, ph, seeds=seeds, retry_cap=args.retry_cap,
                experiment_id=experiment_id,
            )
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
