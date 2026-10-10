import json
import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from cbt_harness import (
    CBTHarness, Generation, parse_plan, parse_state, repetition_candidates,
)
from generate_replay_diagnostic import make_generator


def plan_payload(**updates):
    return {"technique": "근거 기반 질문", "focus": "내담자가 밝힌 걱정", "steps": ["사실과 해석을 검토한다."], "uncertainties": [], **updates}


def state_payload(**updates):
    return {
        "stage": "핵심 탐색", "confirmed_facts": [], "answered_questions": [],
        "rejected_hypotheses": [], "client_feedback": [], "next_action": "이미 나온 답을 활용한다.",
        "client_requested_stop": False, "plan_revision": None, **updates,
    }


class StubGenerator:
    def __init__(self, states=None, responses=None, plan=None):
        self.calls = []
        self.states = list(states or [json.dumps(state_payload(), ensure_ascii=False)] * 12)
        self.responses = list(responses or ["그 답을 함께 살펴볼게요."] * 12)
        self.plan = plan if plan is not None else json.dumps(plan_payload(), ensure_ascii=False)

    def __call__(self, messages, purpose):
        self.calls.append((messages, purpose))
        text = self.plan if purpose == "plan" else self.states.pop(0) if purpose == "state" else self.responses.pop(0)
        return Generation(text, finish_reason="eos")


class CBTHarnessTests(unittest.TestCase):
    def test_plan_generated_once_and_full_history_preserved(self):
        generate = StubGenerator()
        harness = CBTHarness("상담 원칙", generate)
        history = [{"role": "user", "content": "검사를 앞두고 불안해요."}]
        first = harness.respond(history)
        history += [{"role": "assistant", "content": first["response"]}, {"role": "user", "content": "확인한 뒤에도 불안해요."}]
        harness.respond(history)
        self.assertEqual([purpose for _, purpose in generate.calls], ["plan", "state", "response", "state", "response"])
        self.assertEqual(generate.calls[-1][0][1:], history)
        self.assertEqual(len(history), 3)

    def test_feedback_and_rejected_hypothesis_reach_response_prompt(self):
        generate = StubGenerator(states=[json.dumps(state_payload(
            answered_questions=["처음 든 생각은 무엇인가?"],
            rejected_hypotheses=["완벽해야 한다는 기준"], client_feedback=["이미 답한 질문을 반복한다."],
            next_action="오해를 인정하고 실제 걱정의 근거를 검토한다.",
        ), ensure_ascii=False)])
        CBTHarness("상담 원칙", generate).respond([{"role": "user", "content": "완벽해야 한다는 건 아니에요."}])
        prompt = generate.calls[-1][0][0]["content"]
        for phrase in ["처음 든 생각", "완벽해야 한다는 기준", "이미 답한 질문", "실제 걱정의 근거"]:
            self.assertIn(phrase, prompt)

    def test_invalid_plan_falls_back_without_retry(self):
        generate = StubGenerator(plan="잘못된 출력")
        result = CBTHarness("상담 원칙", generate).respond([{"role": "user", "content": "불안해요."}])
        self.assertEqual(result["plan"]["technique"], "미선택")
        self.assertTrue(result["warnings"][0].startswith("plan_fallback"))
        self.assertEqual(len(generate.calls), 3)

    def test_invalid_state_keeps_facts_but_not_stale_stop(self):
        generate = StubGenerator(states=[json.dumps(state_payload(
            confirmed_facts=["품질 검사를 앞두고 있다."], client_requested_stop=True, stage="중단",
        ), ensure_ascii=False), "형식 오류"])
        harness = CBTHarness("상담 원칙", generate)
        first = harness.respond([{"role": "user", "content": "오늘 상담은 그만할게요."}])
        result = harness.respond([
            {"role": "user", "content": "오늘 상담은 그만할게요."},
            {"role": "assistant", "content": first["response"]},
            {"role": "user", "content": "다시 얘기해 볼게요."},
        ])
        self.assertEqual(result["state"]["confirmed_facts"], ["품질 검사를 앞두고 있다."])
        self.assertFalse(result["state"]["client_requested_stop"])
        self.assertNotEqual(result["state"]["stage"], "중단")
        self.assertTrue(result["warnings"][0].startswith("state_fallback"))

    def test_plan_revision_uses_observed_history(self):
        generate = StubGenerator(states=[json.dumps(state_payload(
            plan_revision=plan_payload(technique="행동 실험", focus="반복 확인 행동"),
        ), ensure_ascii=False)])
        result = CBTHarness("상담 원칙", generate).respond([{"role": "user", "content": "자꾸 확인해요."}])
        self.assertEqual(result["plan"]["technique"], "행동 실험")

    def test_invalid_revision_is_not_committed(self):
        generate = StubGenerator(states=[json.dumps(state_payload(
            confirmed_facts=["새 사실"], plan_revision={"technique": "엉뚱한 기법"},
        ), ensure_ascii=False)])
        result = CBTHarness("상담 원칙", generate).respond([{"role": "user", "content": "불안해요."}])
        self.assertEqual(result["state"]["confirmed_facts"], [])
        self.assertEqual(result["plan"]["technique"], "근거 기반 질문")
        self.assertTrue(result["warnings"])

    def test_repeated_counselor_response_is_kept_not_regenerated(self):
        text = "같은 질문을 다시 할게요. 어떤 생각이 드나요?"
        generate = StubGenerator(responses=[text])
        result = CBTHarness("상담 원칙", generate).respond([
            {"role": "user", "content": "불안해요."}, {"role": "assistant", "content": text},
            {"role": "user", "content": "이미 답했어요."},
        ])
        self.assertEqual(result["response"], text)
        self.assertTrue(result["repetition_candidates"]["exact_prior_response"])
        self.assertEqual(sum(purpose == "response" for _, purpose in generate.calls), 1)

    def test_repeated_question_inside_different_response_is_flagged(self):
        metrics = repetition_candidates("이해했어요. 어떤 생각이 드나요?", [
            {"role": "assistant", "content": "그렇군요. 어떤 생각이 드나요?"},
        ])
        self.assertFalse(metrics["exact_prior_response"])
        self.assertEqual(metrics["repeated_question_candidates"][0]["previous_counselor_turns"], [1])
        self.assertFalse(metrics["semantic_repetition_assessed"])

    def test_duplicate_question_within_response(self):
        metrics = repetition_candidates("어떤 생각이 드나요? 어떤 생각이 드나요?", [])
        self.assertTrue(metrics["within_response_duplicate_question"])

    def test_empty_response_fails_without_retry(self):
        generate = StubGenerator(responses=[""])
        with self.assertRaisesRegex(ValueError, "비어"):
            CBTHarness("상담 원칙", generate).respond([{"role": "user", "content": "불안해요."}])
        self.assertEqual(len(generate.calls), 3)

    def test_invalid_histories_fail_before_generation(self):
        for history in [[], [{"role": "assistant", "content": "답"}], [{"role": "user", "content": ""}]]:
            generate = StubGenerator()
            with self.subTest(history=history), self.assertRaises(ValueError):
                CBTHarness("상담 원칙", generate).respond(history)
            self.assertEqual(generate.calls, [])

    def test_schema_validates_types_and_techniques(self):
        for payload in [state_payload(client_requested_stop="false"), state_payload(confirmed_facts="사실"), state_payload(stage="알 수 없음")]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_state(json.dumps(payload))
        with self.assertRaises(ValueError):
            parse_plan(json.dumps(plan_payload(technique="알 수 없음")))

    def test_fenced_json_supported(self):
        plan = parse_plan("```json\n" + json.dumps(plan_payload()) + "\n```")
        self.assertEqual(plan.technique, "근거 기반 질문")

    def test_conditions_and_sessions_do_not_share_state(self):
        first = CBTHarness("상담 원칙", StubGenerator(states=[json.dumps(state_payload(confirmed_facts=["A의 사실"]))]))
        second = CBTHarness("상담 원칙", StubGenerator())
        first.respond([{"role": "user", "content": "A"}])
        result = second.respond([{"role": "user", "content": "B"}])
        self.assertEqual(result["state"]["confirmed_facts"], [])

    def test_plan_at_token_limit_is_not_used(self):
        class CappedGenerator(StubGenerator):
            def __call__(self, messages, purpose):
                result = super().__call__(messages, purpose)
                return Generation(result.text, finish_reason="length") if purpose == "plan" else result
        result = CBTHarness("상담 원칙", CappedGenerator()).respond([{"role": "user", "content": "불안해요."}])
        self.assertEqual(result["plan"]["technique"], "미선택")
        self.assertEqual(result["generation_events"][0]["finish_reason"], "length")


class FakeGenerated(list):
    def __init__(self, text, ended_with_eos=True):
        super().__init__([11, 12, 99 if ended_with_eos else 12])
        self.text = text

    def numel(self):
        return len(self)


class FakeModel:
    def __init__(self):
        self.config = SimpleNamespace(max_position_embeddings=5000)
        self.device = "fake"
        self.adapter_enabled = True
        self.calls = []
        self.outputs = [json.dumps(plan_payload()), json.dumps(state_payload()), "새로운 상담자 응답"]
        self.ended_with_eos = True

    @contextmanager
    def disable_adapter(self):
        self.adapter_enabled = False
        try:
            yield
        finally:
            self.adapter_enabled = True

    def generate(self, **kwargs):
        self.calls.append({"adapter_enabled": self.adapter_enabled, **kwargs})
        return FakeOutput(FakeGenerated(self.outputs.pop(0), self.ended_with_eos))


class FakeOutput:
    def __init__(self, generated):
        self.generated = generated

    def __getitem__(self, key):
        return self.generated


class GeneratorWiringTests(unittest.TestCase):
    def test_adapter_condition_applies_to_plan_state_and_response(self):
        fake_torch = SimpleNamespace(inference_mode=nullcontext)
        tokenizer = SimpleNamespace(eos_token_id=99, pad_token_id=99, decode=lambda generated, **kwargs: generated.text)
        for disabled in [True, False]:
            model = FakeModel()
            with self.subTest(disabled=disabled), patch.dict("sys.modules", {"torch": fake_torch}), patch(
                "generate_replay_diagnostic.tokenize_chat", return_value={"input_ids": SimpleNamespace(shape=(1, 4))}
            ):
                generate = make_generator(model, tokenizer, disable_adapter=disabled, token_limits={"plan": 768, "state": 1536, "response": 384})
                result = CBTHarness("상담 원칙", generate).respond([{"role": "user", "content": "불안해요."}])
            self.assertEqual([call["adapter_enabled"] for call in model.calls], [not disabled] * 3)
            self.assertEqual([call["max_new_tokens"] for call in model.calls], [768, 1536, 384])
            self.assertTrue(model.adapter_enabled)
            self.assertEqual([event["finish_reason"] for event in result["generation_events"]], ["eos"] * 3)

    def test_eos_at_token_limit_is_not_marked_as_truncation(self):
        tokenizer = SimpleNamespace(eos_token_id=99, pad_token_id=99, decode=lambda generated, **kwargs: generated.text)
        for ended_with_eos, expected_reason in [(True, "eos"), (False, "length")]:
            model = FakeModel()
            model.ended_with_eos = ended_with_eos
            with self.subTest(eos=ended_with_eos), patch.dict("sys.modules", {"torch": SimpleNamespace(inference_mode=nullcontext)}), patch(
                "generate_replay_diagnostic.tokenize_chat", return_value={"input_ids": SimpleNamespace(shape=(1, 4))}
            ):
                generate = make_generator(model, tokenizer, disable_adapter=False, token_limits={"response": 3})
                result = generate([], "response")
            self.assertEqual(result.finish_reason, expected_reason)

    def test_sampling_only_applies_to_response(self):
        model = FakeModel()
        tokenizer = SimpleNamespace(eos_token_id=99, pad_token_id=99, decode=lambda generated, **kwargs: generated.text)
        with patch.dict("sys.modules", {"torch": SimpleNamespace(inference_mode=nullcontext)}), patch(
            "generate_replay_diagnostic.tokenize_chat", return_value={"input_ids": SimpleNamespace(shape=(1, 4))}
        ):
            generate = make_generator(
                model, tokenizer, disable_adapter=False, token_limits={"plan": 768, "state": 1536, "response": 384},
                response_temperature=0.6,
            )
            CBTHarness("상담 원칙", generate).respond([{"role": "user", "content": "불안해요."}])
        self.assertEqual([call["do_sample"] for call in model.calls], [False, False, True])
        self.assertNotIn("temperature", model.calls[0])
        self.assertEqual(model.calls[-1]["temperature"], 0.6)

    def test_context_limit_does_not_silently_drop_history(self):
        model = FakeModel()
        model.config.max_position_embeddings = 5
        tokenizer = SimpleNamespace(eos_token_id=99, pad_token_id=99)
        with patch.dict("sys.modules", {"torch": SimpleNamespace(inference_mode=nullcontext)}), patch(
            "generate_replay_diagnostic.tokenize_chat", return_value={"input_ids": SimpleNamespace(shape=(1, 4))}
        ):
            generate = make_generator(model, tokenizer, disable_adapter=False, token_limits={"response": 384})
            with self.assertRaisesRegex(ValueError, "문맥"):
                generate([], "response")
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()
