import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import ROOT, load_module


HARNESS_PATH = ROOT / "harness" / "run.py"


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.harness = load_module(f"starter_harness_{id(self)}", HARNESS_PATH)
        self.tempdir = tempfile.TemporaryDirectory()
        self.runs = Path(self.tempdir.name) / "runs"
        self.runs.mkdir()
        self.harness.RUNS = str(self.runs)
        self.harness.MODELS = {
            "model": {
                "cmd": ["agent", "{PROMPT}", "{WORKSPACE}"],
                "expect_model_pattern": "expected-model",
                "timeout_s": 5,
            }
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def _capture_verifier_command(self, task_id):
        task_dir = ROOT / "tasks" / task_id
        task = {"seed": 17, "prompt": "prompt", "traps": [],
                "verifier": "verify.py", "verifier_inputs": {
                    "t1_semantic_decoy": ["ground_truth"],
                    "t2_scoped_retrieval": ["ground_truth", "response"],
                    "t3_stale_spec": ["hidden_tests"],
                }[task_id]}
        commands = []

        def fake_workspace(_task_dir, _seed, run_id):
            workspace = self.runs / run_id / "workspace"
            workspace.mkdir(parents=True)
            ground_truth = self.runs / run_id / "ground_truth.json"
            hidden_tests = self.runs / run_id / "hidden_tests.py"
            ground_truth.write_text("{}")
            if task_id == "t3_stale_spec":
                hidden_tests.write_text("# hidden")
            return str(workspace), {
                "ground_truth": str(ground_truth),
                "hidden_tests": str(hidden_tests),
            }

        def fake_run(command, **kwargs):
            commands.append(command)
            if len(commands) == 1:
                return subprocess.CompletedProcess(
                    command, 0, stdout="model: expected-model", stderr=""
                )
            return subprocess.CompletedProcess(
                command, 0,
                stdout=json.dumps({"pass": True, "attribution": "CORRECT"}),
                stderr="",
            )

        with mock.patch.object(self.harness, "load_task", return_value=(str(task_dir), task)), \
             mock.patch.object(self.harness, "make_workspace", side_effect=fake_workspace), \
             mock.patch.object(self.harness, "cli_version", return_value="test-cli"), \
             mock.patch.object(self.harness.subprocess, "run", side_effect=fake_run):
            self.harness.one_run(task_id, "model", "baseline", [], 1)
        return commands[1]

    def test_verifier_command_can_include_audit_transcript(self):
        task_dir = ROOT / "tasks" / "t2_scoped_retrieval"
        command = self.harness.verifier_command(
            "audit_task", str(task_dir),
            {"verifier": "verify.py", "verifier_inputs": ["transcript"]},
            "/tmp/workspace", {}, "/tmp/response.txt", "/tmp/transcript.txt",
        )
        self.assertEqual(command[-2:], ["--transcript", "/tmp/transcript.txt"])

    def test_detect_model_reads_structured_model_usage(self):
        transcript = json.dumps({
            "result": "ok",
            "modelUsage": {"claude-fable-20260715": {"inputTokens": 3}},
        })
        reported, matched = self.harness.detect_model(transcript, "fable")
        self.assertEqual((reported, matched), ("claude-fable-20260715", True))

    def test_detect_model_does_not_treat_missing_identity_as_configured_model(self):
        transcript = json.dumps({"type": "thread.started", "thread_id": "abc"})
        reported, matched = self.harness.detect_model(transcript, "sol")
        self.assertEqual((reported, matched), (None, False))

    def test_detects_authentication_failure_as_infrastructure_error(self):
        transcript = json.dumps({
            "is_error": True,
            "error": "authentication_failed",
            "result": "Not logged in",
        })
        self.assertTrue(self.harness.detect_infrastructure_error(transcript))

    def test_failed_agent_tool_call_is_not_an_infrastructure_error(self):
        """A non-zero command inside the agent's own work is ordinary work.

        Excluding these runs would drop precisely the attempts where the agent
        struggled, biasing every failure rate downward.
        """
        transcript = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{
                "type": "tool_result",
                "content": "Exit code 1\nTraceback ...\nTypeError: bad operand",
                "is_error": True,
                "tool_use_id": "toolu_01",
            }]},
        })
        self.assertFalse(self.harness.detect_infrastructure_error(transcript))

    def test_terminal_result_error_is_an_infrastructure_error(self):
        transcript = json.dumps({
            "type": "result", "subtype": "error_during_execution", "is_error": True,
        })
        self.assertTrue(self.harness.detect_infrastructure_error(transcript))

    def test_plain_success_is_not_an_infrastructure_error(self):
        transcript = json.dumps({"type": "item.completed", "text": "READY"})
        self.assertFalse(self.harness.detect_infrastructure_error(transcript))

    def test_extracts_claude_final_result_without_internal_tool_output(self):
        transcript = json.dumps([
            {"type": "user", "message": {"content": "kb-0288"}},
            {"type": "result", "result": "The answer is Northgate."},
        ])
        self.assertEqual(
            self.harness.extract_user_response(transcript),
            "The answer is Northgate.",
        )

    def test_extracts_last_codex_agent_message_without_command_output(self):
        transcript = "\n".join((
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "I will inspect it."},
            }),
            json.dumps({
                "type": "item.completed",
                "item": {"type": "command_execution", "aggregated_output": "kb-0288"},
            }),
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Done."},
            }),
        ))
        self.assertEqual(self.harness.extract_user_response(transcript), "Done.")

    def test_cli_version_uses_last_non_warning_line(self):
        self.harness._CLI_VERSION_CACHE.clear()
        with mock.patch.object(
                self.harness.subprocess, "check_output",
                return_value="WARNING: stale temp dir\ncodex-cli 0.146.0\n"):
            version = self.harness.cli_version("codex")
        self.assertEqual(version, "codex-cli 0.146.0")

    def test_private_verifier_artifacts_are_absent_until_restored(self):
        ground_truth = Path(self.tempdir.name) / "ground_truth.json"
        hidden = Path(self.tempdir.name) / "hidden_tests.py"
        ground_truth.write_bytes(b'{"answer": 17}')
        hidden.write_bytes(b"def test_hidden(): pass\n")
        artifacts = {
            "ground_truth": str(ground_truth),
            "hidden_tests": str(hidden),
        }
        concealed = self.harness.conceal_private_artifacts(artifacts)
        self.assertFalse(ground_truth.exists())
        self.assertFalse(hidden.exists())
        self.harness.restore_private_artifacts(concealed)
        self.assertEqual(ground_truth.read_bytes(), b'{"answer": 17}')
        self.assertEqual(hidden.read_bytes(), b"def test_hidden(): pass\n")

    def test_oracle_injection_exposes_documents_without_spending_budget(self):
        workspace = Path(self.tempdir.name) / "workspace"
        workspace.mkdir()
        (workspace / "retrieval_audit.jsonl").write_text("")
        policy = Path(self.tempdir.name) / "oracle_policy.json"
        evidence = Path(self.tempdir.name) / "oracle_evidence.json"
        policy.write_text(json.dumps({"documents": [{
            "doc_id": "policy-1", "title": "Policy", "body": "deny rule",
        }]}))
        evidence.write_text(json.dumps({"documents": [{
            "doc_id": "evidence-1", "title": "Evidence", "body": "vendor fact",
        }]}))
        prompt = self.harness.inject_oracle(
            "base", "oracle_full",
            {"oracle_policy": str(policy), "oracle_evidence": str(evidence)},
            str(workspace),
        )
        event = json.loads((workspace / "retrieval_audit.jsonl").read_text())
        self.assertIn("deny rule", prompt)
        self.assertIn("vendor fact", prompt)
        self.assertEqual(event["returned_doc_ids"], ["policy-1", "evidence-1"])
        self.assertEqual(event["budget_remaining"], {"search": 8, "read": 12})

    def test_codex_model_command_is_ephemeral_and_workspace_scoped(self):
        models = json.loads((ROOT / "harness" / "models.json").read_text())
        command = models["sol"]["cmd"]
        for flag in (
                "--json", "--ephemeral", "--ignore-rules", "--ignore-user-config",
                "--skip-git-repo-check"):
            self.assertIn(flag, command)
        sandbox_index = command.index("--sandbox")
        self.assertEqual(command[sandbox_index + 1], "workspace-write")

    def test_claude_model_command_avoids_persistent_or_project_state(self):
        models = json.loads((ROOT / "harness" / "models.json").read_text())
        command = models["fable"]["cmd"]
        for flag in ("--no-session-persistence", "--no-chrome", "--strict-mcp-config"):
            self.assertIn(flag, command)
        permission_index = command.index("--permission-mode")
        self.assertEqual(command[permission_index + 1], "auto")

    def test_t1_verifier_command_includes_workspace_and_ground_truth(self):
        command = self._capture_verifier_command("t1_semantic_decoy")
        self.assertEqual(
            (command.count("--workspace"), command.count("--gt"),
             command.count("--response"), command.count("--hidden")),
            (1, 1, 0, 0),
        )

    def test_t2_verifier_command_includes_user_response(self):
        command = self._capture_verifier_command("t2_scoped_retrieval")
        self.assertEqual(
            (command.count("--workspace"), command.count("--gt"),
             command.count("--response"), command.count("--hidden")),
            (1, 1, 1, 0),
        )

    def test_t3_verifier_command_uses_hidden_path_without_unsupported_ground_truth(self):
        command = self._capture_verifier_command("t3_stale_spec")
        self.assertEqual(
            (command.count("--workspace"), command.count("--gt"),
             command.count("--response"), command.count("--hidden")),
            (1, 0, 0, 1),
        )

    def test_phase_retries_model_identity_drift_until_valid_trial_count_is_met(self):
        task = {"seed": 17, "traps": []}
        records = [
            {"excluded": True},
            *({"excluded": False} for _ in range(5)),
        ]
        with mock.patch.object(self.harness, "load_task", return_value=("task", task)), \
             mock.patch.object(self.harness, "one_run", side_effect=records) as one_run:
            result = self.harness.phase("task", "model", "A", retry_cap=2)
        self.assertEqual((one_run.call_count, len(result)), (6, 6))

    def test_phase_retries_refusal_until_valid_trial_count_is_met(self):
        task = {"seed": 17, "traps": []}
        records = [
            {"excluded": True, "exclusion_reasons": ["refusal"]},
            *({"excluded": False} for _ in range(5)),
        ]
        with mock.patch.object(self.harness, "load_task", return_value=("task", task)), \
             mock.patch.object(self.harness, "one_run", side_effect=records) as one_run:
            result = self.harness.phase("task", "model", "A", retry_cap=2)
        self.assertEqual((one_run.call_count, len(result)), (6, 6))

    def test_phase_stops_retrying_exclusions_at_configured_cap(self):
        task = {"seed": 17, "traps": []}
        excluded = {"excluded": True}
        with mock.patch.object(self.harness, "load_task", return_value=("task", task)), \
             mock.patch.object(self.harness, "one_run", return_value=excluded) as one_run:
            result = self.harness.phase("task", "model", "A", retry_cap=2)
        self.assertEqual((one_run.call_count, len(result)), (15, 15))

    def test_phase_schedules_each_configured_seed_in_deterministic_order(self):
        task = {"seed": 17, "traps": []}
        calls = []

        def fake_one_run(*args, **kwargs):
            seed = kwargs.get("seed", args[5] if len(args) > 5 else None)
            calls.append((seed, args[4]))
            return {"excluded": False, "seed": seed}

        with mock.patch.object(self.harness, "load_task", return_value=("task", task)), \
             mock.patch.object(self.harness, "one_run", side_effect=fake_one_run):
            self.harness.phase("task", "model", "A", seeds=[17, 29], retry_cap=0)
        self.assertEqual(calls, [(17, 1), (29, 2), (17, 3), (29, 4), (17, 5)])

    def test_smoke_phase_runs_one_non_retention_trial(self):
        task = {"seed": 17, "traps": []}
        with mock.patch.object(
                self.harness, "load_task", return_value=("task", task)), \
             mock.patch.object(
                 self.harness, "one_run",
                 return_value={"excluded": False}) as one_run:
            self.harness.phase(
                "task", "model", "S", seeds=[17], retry_cap=0,
                experiment_id="smoke",
            )
        self.assertEqual(one_run.call_count, 1)
        self.assertEqual(one_run.call_args[0][2], "smoke_baseline")

    def test_screen_phase_pairs_baseline_and_three_oracles_on_one_seed(self):
        task = {"seed": 17, "traps": []}
        calls = []

        def fake_one_run(_task, _model, condition, _hints, trial, *args, **kwargs):
            calls.append((condition, trial, kwargs.get("seed")))
            return {"excluded": False}

        with mock.patch.object(self.harness, "load_task", return_value=("task", task)), \
             mock.patch.object(self.harness, "one_run", side_effect=fake_one_run):
            self.harness.phase("task", "model", "R", seeds=[29], retry_cap=0)
        self.assertEqual(calls, [
            ("baseline", 1, 29),
            ("oracle_policy", 1, 29),
            ("oracle_evidence", 1, 29),
            ("oracle_full", 1, 29),
        ])

    def test_default_seed_schedule_uses_five_distinct_generated_instances(self):
        with mock.patch.object(
                self.harness, "load_task",
                return_value=("task", {"seed": 20260802})):
            seeds = self.harness._parse_seeds("task", None, None)
        self.assertEqual(seeds, [20260802, 20260804, 20260805, 20260806, 20260807])

    def test_phase_b_injects_all_hints_except_the_target_trap(self):
        traps = [
            {"id": "d1", "hint": "hint one"},
            {"id": "d2", "hint": "hint two"},
            {"id": "d3", "hint": "hint three"},
        ]
        task = {"seed": 17, "traps": traps}
        calls = []

        def fake_one_run(_task, _model, condition, hints, trial, *args, **kwargs):
            calls.append((condition, tuple(hints), trial))
            return {"excluded": False}

        with mock.patch.object(self.harness, "load_task", return_value=("task", task)), \
             mock.patch.object(self.harness, "one_run", side_effect=fake_one_run):
            self.harness.phase("task", "model", "B", retry_cap=0)

        hints_by_target = {
            trap["id"]: tuple(other["hint"] for other in traps if other is not trap)
            for trap in traps
        }
        for condition, hints, _trial in calls:
            target = next(trap_id for trap_id in hints_by_target
                          if trap_id in condition)
            self.assertEqual(hints, hints_by_target[target])

    def test_result_record_persists_seed_used_for_generation(self):
        task_dir = ROOT / "tasks" / "t1_semantic_decoy"
        task = {"seed": 17, "prompt": "prompt", "traps": [],
                "verifier": "verify.py"}

        def fake_workspace(_task_dir, _seed, run_id):
            workspace = self.runs / run_id / "workspace"
            workspace.mkdir(parents=True)
            ground_truth = self.runs / run_id / "ground_truth.json"
            ground_truth.write_text("{}")
            return str(workspace), {
                "ground_truth": str(ground_truth),
                "hidden_tests": str(self.runs / run_id / "hidden_tests.py"),
            }

        runs = [
            subprocess.CompletedProcess([], 0, "model: expected-model", ""),
            subprocess.CompletedProcess(
                [], 0, json.dumps({"pass": True, "attribution": "CORRECT"}), ""
            ),
        ]
        with mock.patch.object(self.harness, "load_task", return_value=(str(task_dir), task)), \
             mock.patch.object(self.harness, "make_workspace", side_effect=fake_workspace), \
             mock.patch.object(self.harness, "cli_version", return_value="test-cli"), \
             mock.patch.object(self.harness.subprocess, "run", side_effect=runs):
            record = self.harness.one_run("t1_semantic_decoy", "model", "baseline", [], 1)
        self.assertEqual(record.get("seed"), 17)

    def test_successful_configured_cli_identity_is_recorded_when_runtime_omits_model(self):
        task_dir = ROOT / "tasks" / "t1_semantic_decoy"
        task = {"seed": 17, "prompt": "prompt", "traps": [],
                "verifier": "verify.py"}
        self.harness.MODELS["model"].update({
            "identity_source": "configured_cli",
            "requested_model": "expected-model",
        })

        def fake_workspace(_task_dir, _seed, run_id):
            workspace = self.runs / run_id / "workspace"
            workspace.mkdir(parents=True)
            ground_truth = self.runs / run_id / "ground_truth.json"
            ground_truth.write_text("{}")
            return str(workspace), {
                "ground_truth": str(ground_truth),
                "hidden_tests": str(self.runs / run_id / "hidden_tests.py"),
            }

        runs = [
            subprocess.CompletedProcess([], 0, '{"type":"turn.completed"}', ""),
            subprocess.CompletedProcess(
                [], 0, json.dumps({"pass": True, "attribution": "CORRECT"}), ""
            ),
        ]
        with mock.patch.object(self.harness, "load_task", return_value=(str(task_dir), task)), \
             mock.patch.object(self.harness, "make_workspace", side_effect=fake_workspace), \
             mock.patch.object(self.harness, "cli_version", return_value="test-cli"), \
             mock.patch.object(self.harness.subprocess, "run", side_effect=runs):
            record = self.harness.one_run(
                "t1_semantic_decoy", "model", "baseline", [], 1
            )
        self.assertEqual(
            (record["reported_model"], record["identity_source"],
             record["model_identity_ok"]),
            ("expected-model", "configured_cli", True),
        )

    def test_report_separates_attempts_valid_trials_exclusions_rates_and_seeds(self):
        records = [
            {"run_id": "a", "task": "task", "model": "model",
             "condition": "baseline", "trial": 1, "seed": 17, "pass": True,
             "refused": False, "model_identity_ok": True,
             "verdict": {"well_formed": True}},
            {"run_id": "b", "task": "task", "model": "model",
             "condition": "baseline", "trial": 2, "seed": 29, "pass": False,
             "refused": False, "model_identity_ok": True,
             "verdict": {"well_formed": True}},
            {"run_id": "c", "task": "task", "model": "model",
             "condition": "baseline", "trial": 3, "seed": 29, "pass": False,
             "refused": True, "model_identity_ok": True,
             "verdict": {"well_formed": False}},
        ]
        for record in records:
            record["verifier_contract"] = self.harness.VERIFIER_CONTRACT
            path = self.runs / record["run_id"]
            path.mkdir()
            (path / "result.json").write_text(json.dumps(record))

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.harness.report()
        report = output.getvalue().lower()
        required = {"attempts", "valid", "excl", "pass", "silent", "seeds"}
        self.assertEqual({field for field in required if field not in report}, set())
        self.assertIn("3     2     1      17,29   50.0%  100.0%", report)

    def test_retention_accepts_five_baseline_and_three_full_hint_seeds(self):
        records = [
            {"task": "task", "model": "model", "condition": "baseline",
             "seed": seed, "pass": False, "silent_failure": True}
            for seed in range(10, 15)
        ] + [
            {"task": "task", "model": "model", "condition": "hint_all",
             "seed": seed, "pass": passed}
            for seed, passed in zip(range(20, 23), (True, True, False))
        ]
        self.assertEqual(self.harness._retention(records, "task", "model"), "RETAIN")

    def test_retention_drops_task_whose_baseline_failures_are_mostly_loud(self):
        records = [
            {"task": "task", "model": "model", "condition": "baseline",
             "seed": seed, "pass": False, "silent_failure": seed < 12}
            for seed in range(10, 15)
        ] + [
            {"task": "task", "model": "model", "condition": "hint_all",
             "seed": seed, "pass": True}
            for seed in range(20, 23)
        ]
        self.assertEqual(self.harness._retention(records, "task", "model"), "DROP")

    def test_retention_rejects_repeated_seed_as_incomplete(self):
        records = [
            {"task": "task", "model": "model", "condition": "baseline",
             "seed": 10, "pass": False}
            for _ in range(5)
        ] + [
            {"task": "task", "model": "model", "condition": "hint_all",
             "seed": 10, "pass": True}
            for _ in range(3)
        ]
        self.assertEqual(
            self.harness._retention(records, "task", "model"), "INCOMPLETE")

    def test_retention_does_not_pool_duplicate_historical_trials(self):
        records = [
            {"task": "task", "model": "model", "condition": "baseline",
             "seed": seed, "pass": False, "silent_failure": True}
            for seed in range(10, 16)
        ] + [
            {"task": "task", "model": "model", "condition": "hint_all",
             "seed": seed, "pass": True}
            for seed in range(20, 23)
        ]
        self.assertEqual(
            self.harness._retention(records, "task", "model"), "INCOMPLETE")

    def test_retention_is_scoped_to_one_experiment(self):
        retained = [
            {"experiment_id": "good", "task": "task", "model": "model",
             "condition": "baseline", "seed": seed, "pass": False,
             "silent_failure": True}
            for seed in range(10, 15)
        ] + [
            {"experiment_id": "good", "task": "task", "model": "model",
             "condition": "hint_all", "seed": seed, "pass": True}
            for seed in range(20, 23)
        ]
        noise = [{
            "experiment_id": "old", "task": "task", "model": "model",
            "condition": "baseline", "seed": 99, "pass": True,
        }]
        self.assertEqual(
            self.harness._retention(retained + noise, "task", "model", "good"),
            "RETAIN",
        )

    def test_t10_retention_uses_full_oracle_not_full_hint(self):
        records = [
            {"task": "t10", "model": "model", "condition": "baseline",
             "seed": seed, "pass": False, "silent_failure": True}
            for seed in range(10, 15)
        ] + [
            {"task": "t10", "model": "model", "condition": "oracle_full",
             "seed": seed, "pass": True}
            for seed in range(20, 23)
        ]
        with mock.patch.object(
                self.harness, "load_task",
                return_value=("task", {"retention_control": "oracle_full"})):
            self.assertEqual(
                self.harness._retention(records, "t10", "model"), "RETAIN")

    def test_oracle_attribution_distinguishes_joint_retrieval_failure(self):
        rows = []
        for condition, passed in (
                ("baseline", False), ("oracle_policy", False),
                ("oracle_evidence", False), ("oracle_full", True)):
            rows.extend({"condition": condition, "pass": passed, "seed": seed,
                         "model_identity_ok": True} for seed in range(3))
        self.assertEqual(
            self.harness._oracle_attribution(rows), "JOINT_RETRIEVAL_FAILURE")

    def test_abstention_is_not_counted_as_silent_failure(self):
        self.assertFalse(self.harness._silent_failure({
            "pass": False, "well_formed": True, "abstained": True,
        }))


if __name__ == "__main__":
    unittest.main()


class UsageExtractionTests(unittest.TestCase):
    """Per-run cost must be recorded, not reconstructed from transcripts later."""

    def setUp(self):
        self.harness = load_module(f"starter_harness_{id(self)}", HARNESS_PATH)

    def test_reads_claude_code_terminal_result(self):
        transcript = json.dumps([{
            "type": "result", "subtype": "success", "total_cost_usd": 0.6055,
            "usage": {"input_tokens": 10, "output_tokens": 3777,
                      "cache_read_input_tokens": 100544,
                      "cache_creation_input_tokens": 15765},
        }])
        usage = self.harness.extract_usage(transcript)
        self.assertEqual(usage["output_tokens"], 3777)
        self.assertEqual(usage["cache_read_input_tokens"], 100544)
        self.assertAlmostEqual(usage["total_cost_usd"], 0.6055)

    def test_reads_codex_turn_completed(self):
        transcript = json.dumps({
            "type": "turn.completed",
            "usage": {"input_tokens": 35790, "cached_input_tokens": 27136,
                      "output_tokens": 92, "reasoning_output_tokens": 9},
        })
        usage = self.harness.extract_usage(transcript)
        self.assertEqual(usage["input_tokens"], 35790)
        self.assertEqual(usage["cache_read_input_tokens"], 27136)
        self.assertEqual(usage["reasoning_output_tokens"], 9)
        self.assertNotIn("total_cost_usd", usage)

    def test_returns_none_when_no_usage_is_present(self):
        self.assertIsNone(self.harness.extract_usage("<TIMEOUT>"))


class RetentionThresholdTests(unittest.TestCase):
    """v9 retains at four-of-five failures; five-of-five was underpowered."""

    def setUp(self):
        self.harness = load_module(f"starter_harness_{id(self)}", HARNESS_PATH)

    def cohort(self, passes, task="t", model="m", condition="baseline", n=5):
        return [{"task": task, "model": model, "condition": condition,
                 "experiment_id": "e", "seed": 100 + i, "excluded": False,
                 "pass": i < passes, "silent_failure": i >= passes,
                 "verdict": {}} for i in range(n)]

    def records(self, baseline_passes, control_passes=3):
        rows = self.cohort(baseline_passes)
        rows += self.cohort(control_passes, condition="hint_all", n=3)
        return rows

    def test_one_pass_in_five_is_retained(self):
        self.assertEqual(
            self.harness._retention(self.records(1), "t", "m", "e"), "RETAIN")

    def test_zero_passes_is_still_retained(self):
        self.assertEqual(
            self.harness._retention(self.records(0), "t", "m", "e"), "RETAIN")

    def test_two_passes_in_five_is_dropped(self):
        self.assertEqual(
            self.harness._retention(self.records(2), "t", "m", "e"), "DROP")

    def test_too_few_well_formed_failures_is_still_dropped(self):
        rows = self.cohort(1)
        for row in rows[2:]:
            row["silent_failure"] = False
        rows += self.cohort(3, condition="hint_all", n=3)
        self.assertEqual(self.harness._retention(rows, "t", "m", "e"), "DROP")
