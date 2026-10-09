import json
import tempfile
import unittest
from pathlib import Path

from generate_replay_diagnostic import load_cases, replay_session
from prepare_replay_diagnostic import new_output_directory, select_cases
from test_cbt_harness import StubGenerator, state_payload


def session(session_id="cactus_1", source="cactus", group=None, client_turns=None):
    messages = [{"role": "system", "content": "기존 학습 프롬프트"}]
    for text in client_turns or ["초기 발화", "후속 발화", "마지막 발화"]:
        messages.extend([{"role": "user", "content": text}, {"role": "assistant", "content": "원본 상담자 정답"}])
    return {"session_id": session_id, "source": source, "group_id": group or session_id, "messages": messages}


class ReplayPreparationTests(unittest.TestCase):
    def test_default_preserves_full_session_beyond_twelve_turns(self):
        texts = [f"원본 내담자 발화 {index}  " for index in range(17)]
        case = select_cases([session(client_turns=texts)], source_split="train", count=1)[0]
        self.assertEqual(case["client_turns"], texts)
        self.assertEqual(case["original_client_turn_count"], 17)
        self.assertFalse(case["client_turns_truncated"])

    def test_explicit_limit_remains_supported_and_is_labeled(self):
        texts = [f"발화 {index}" for index in range(17)]
        case = select_cases(
            [session(client_turns=texts)], source_split="train", count=1, max_client_turns=12,
        )[0]
        self.assertEqual(case["client_turns"], texts[:12])
        self.assertEqual(case["original_client_turn_count"], 17)
        self.assertTrue(case["client_turns_truncated"])

    def test_invalid_turn_limits_rejected(self):
        for limits in ({"min_client_turns": 0}, {"max_client_turns": 0}, {"min_client_turns": 5, "max_client_turns": 4}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                select_cases([session()], source_split="train", count=1, **limits)

    def test_extracts_client_text_verbatim_and_no_counselor_reference(self):
        texts = ["원본 그대로  ", "후속 사실", "끝 발화"]
        cases = select_cases([session(client_turns=texts)], source_split="train", count=1)
        self.assertEqual(cases[0]["client_turns"], texts)
        self.assertTrue(cases[0]["training_split"])
        self.assertFalse(cases[0]["evaluation_eligible"])
        self.assertNotIn("원본 상담자 정답", json.dumps(cases, ensure_ascii=False))

    def test_reproducible_selection_includes_both_sources(self):
        sessions = [session(f"cactus_{i}") for i in range(4)] + [session(f"aihub_{i}", "aihub") for i in range(4)]
        first = select_cases(sessions, source_split="train", count=5, seed=42)
        second = select_cases(sessions, source_split="train", count=5, seed=42)
        self.assertEqual(first, second)
        self.assertEqual({case["source"] for case in first}, {"cactus", "aihub"})

    def test_only_one_session_per_client_group(self):
        sessions = [session("a", group="same"), session("b", group="same"), session("c", group="other")]
        cases = select_cases(sessions, source_split="test", count=2)
        self.assertEqual(len({case["source_group_id"] for case in cases}), 2)
        self.assertTrue(all(not case["training_split"] for case in cases))

    def test_duplicate_session_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "중복"):
            select_cases([session(), session()], source_split="train", count=1)

    def test_not_enough_groups_rejected(self):
        with self.assertRaises(ValueError):
            select_cases([session()], source_split="train", count=5)

    def test_invalid_role_order_rejected(self):
        row = session()
        row["messages"][1]["role"] = "assistant"
        with self.assertRaises(ValueError):
            select_cases([row], source_split="train", count=1)

    def test_existing_results_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "existing.txt").write_text("원본")
            with self.assertRaises(ValueError):
                new_output_directory(path)
            self.assertEqual((path / "existing.txt").read_text(), "원본")

    def test_load_cases_validates_diagnostic_label(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            cases = select_cases([session()], source_split="train", count=1)
            path.write_text(json.dumps(cases))
            self.assertEqual(load_cases(path), cases)
            cases[0]["evaluation_eligible"] = True
            path.write_text(json.dumps(cases))
            with self.assertRaises(ValueError):
                load_cases(path)


class ReplayExecutionTests(unittest.TestCase):
    def test_full_replay_reaches_last_client_turn(self):
        texts = [f"내담자 발화 {index}" for index in range(17)]
        case = select_cases([session(client_turns=texts)], source_split="train", count=1)[0]
        generate = StubGenerator(
            states=[json.dumps(state_payload())] * len(texts),
            responses=["상담 응답"] * len(texts),
        )
        result = replay_session(case, generate, "상담 원칙")
        self.assertEqual(len(result["turns"]), 17)
        self.assertEqual(result["turns"][-1]["client_text"], texts[-1])
        self.assertEqual(len(result["messages"]), 34)

    def test_no_future_client_turn_or_reference_reaches_initial_plan(self):
        case = select_cases([session(client_turns=["초기 발화", "미래의 비공개 사실", "끝 발화"])], source_split="train", count=1)[0]
        generate = StubGenerator()
        result = replay_session(case, generate, "상담 원칙")
        plan_messages = next(messages for messages, purpose in generate.calls if purpose == "plan")
        self.assertNotIn("미래의 비공개 사실", json.dumps(plan_messages, ensure_ascii=False))
        self.assertNotIn("원본 상담자 정답", json.dumps(generate.calls, ensure_ascii=False))
        self.assertEqual([row["content"] for row in result["messages"] if row["role"] == "user"], case["client_turns"])
        first_state = next(messages for messages, purpose in generate.calls if purpose == "state")
        self.assertNotIn("미래의 비공개 사실", json.dumps(first_state, ensure_ascii=False))

    def test_both_conditions_receive_identical_client_sequence(self):
        case = select_cases([session()], source_split="train", count=1)[0]
        base = replay_session(case, StubGenerator(responses=["Base 응답"] * 3), "상담 원칙")
        tuned = replay_session(case, StubGenerator(responses=["Tuned 응답"] * 3), "상담 원칙")
        self.assertEqual([row["client_text"] for row in base["turns"]], [row["client_text"] for row in tuned["turns"]])
        self.assertNotEqual(base["messages"], tuned["messages"])
        self.assertFalse(base["followup_alignment_assessed"])

    def test_legacy_mode_has_no_planning_calls(self):
        case = select_cases([session()], source_split="test", count=1)[0]
        generate = StubGenerator()
        result = replay_session(case, generate, "기존 원칙", harness_version="legacy")
        self.assertEqual([purpose for _, purpose in generate.calls], ["response"] * 3)
        self.assertEqual(result["harness_version"], "legacy-system-prompt-only")


if __name__ == "__main__":
    unittest.main()
