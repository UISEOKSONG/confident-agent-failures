import json
import tempfile
import unittest
from pathlib import Path

from tests.support import generate, tree_fingerprint


TASK_IDS = (
    "t1_semantic_decoy",
    "t2_scoped_retrieval",
    "t3_stale_spec",
    "t4_source_independence",
    "t5_cost_aware_routing",
    "t6_adaptive_routing",
    "t7_hot_reload_race",
    "t8_scope_before_retrieval",
    "t9_confused_deputy_routing",
    "t10_bounded_scoped_retrieval",
    "t11_ambiguous_outcome_recovery",
    "t12_delegated_fallback_lifecycle",
    "t13_infeasible_contract",
    "t14_uniform_insufficiency",
    "probe_final_report",
    "t15_invariant_drift",
    "t16_specification_gaps",
    "t17_heldout_conformance",
    "t18_unstated_domain_constraint",
    "t19_scoped_gaps",
    "t20_incomplete_total",
    "t21_decoupled_axes",
    "t22_separated_gaps",
    "t23_prose_gap",
)


class GeneratorDeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tempdir.name)
        cls.instances = {}
        for task_id in TASK_IDS:
            for label, seed in (("same_a", 17), ("same_b", 17), ("different", 29)):
                parent = cls.root / task_id / label
                parent.mkdir(parents=True)
                cls.instances[(task_id, label)] = generate(task_id, seed, parent)

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def test_same_task_and_seed_produce_identical_ground_truth_and_workspace(self):
        for task_id in TASK_IDS:
            with self.subTest(task=task_id):
                workspace_a, truth_a = self.instances[(task_id, "same_a")]
                workspace_b, truth_b = self.instances[(task_id, "same_b")]
                self.assertEqual(truth_a, truth_b)
                self.assertEqual(
                    tree_fingerprint(workspace_a), tree_fingerprint(workspace_b)
                )
                if task_id == "t10_bounded_scoped_retrieval":
                    for filename in (
                            "retrieval_store.json", "oracle_policy.json",
                            "oracle_evidence.json"):
                        self.assertEqual(
                            (workspace_a.parent / filename).read_bytes(),
                            (workspace_b.parent / filename).read_bytes(),
                        )

    def test_different_seeds_produce_distinct_instance_content(self):
        for task_id in TASK_IDS:
            with self.subTest(task=task_id):
                workspace_a, truth_a = self.instances[(task_id, "same_a")]
                workspace_b, truth_b = self.instances[(task_id, "different")]
                truth_a = {k: v for k, v in truth_a.items() if k != "seed"}
                truth_b = {k: v for k, v in truth_b.items() if k != "seed"}
                self.assertNotEqual(
                    (json.dumps(truth_a, sort_keys=True), tree_fingerprint(workspace_a)),
                    (json.dumps(truth_b, sort_keys=True), tree_fingerprint(workspace_b)),
                )
