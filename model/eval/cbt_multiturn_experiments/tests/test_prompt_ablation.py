import json
import unittest
from pathlib import Path
from unittest.mock import patch

from audit_prompt_ablation import review_experiment


class PromptAblationAuditTests(unittest.TestCase):
    def review(self, changed=None, generation_count=1):
        manifest = {
            "status": "complete", "system_prompt_sha256": "test-hash",
            "harness_version": "legacy-system-prompt-only", "external_api_calls": 0,
            "model_name": "test-model", "adapter_path": "test-adapter",
            "generation": {"do_sample": False}, "cases_file_sha256": "test-cases",
            "client_turn_counts": {"R001": 1}, "source_code_sha256": {},
        }
        variant_manifest = {**manifest, **(changed or {})}
        metrics = {
            "counselor_turns": 1, "literal_duplicate_turns": 0,
            "normalized_duplicate_turns": 0, "similarity_ge_0_9_candidate_turns": 0,
            "repeated_question_candidate_turns": 0, "response_tokens_le_10_turns": 0,
            "response_length_cap_turns": 0,
        }
        summary = {"definitions": {}, "sessions": [
            {"case_id": "R001", "condition": condition, **metrics}
            for condition in ("base", "tuned")
        ]}
        with patch("audit_prompt_ablation.audit", return_value=(summary, "test transcript")), \
             patch.object(Path, "read_text", side_effect=[json.dumps(manifest), json.dumps(variant_manifest)]), \
             patch("audit_prompt_ablation.file_hash", return_value="test-hash"), \
             patch("audit_prompt_ablation.read_jsonl", return_value=[{"generation_events": [{"purpose": "response"}] * generation_count}]):
            return review_experiment(Path("test-results"), Path("test-cases"), Path("test-prompts"))

    def test_maps_all_four_conditions(self):
        summary, _ = self.review()
        self.assertEqual([row["label"] for row in summary["totals"]], list("ABCD"))
        self.assertEqual(summary["counselor_turn_count"], 4)

    def test_rejects_generation_setting_difference(self):
        with self.assertRaisesRegex(ValueError, "Uncontrolled"):
            self.review({"generation": {"do_sample": True}})

    def test_rejects_planning_harness(self):
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.review({"harness_version": "cbt-plan-state-v2"})

    def test_rejects_hidden_generation_calls(self):
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.review(generation_count=2)


if __name__ == "__main__":
    unittest.main()
