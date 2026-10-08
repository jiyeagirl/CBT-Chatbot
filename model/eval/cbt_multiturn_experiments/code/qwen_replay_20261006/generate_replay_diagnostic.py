"""동일한 원본 내담자 발화를 Base/QLoRA에 고정 재생하는 진단 실행기.

두 조건은 각자의 계획·진행 메모를 만들되 프롬프트와 생성 설정은 동일하다.
외부 API를 사용하지 않으며 CUDA에서만 모델을 로드한다.
"""

from __future__ import annotations

import argparse
import json
import time
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cbt_harness import CBTHarness, Generation, HARNESS_VERSION, PLAN_PROMPT, STATE_PROMPT, repetition_candidates
from generate_multiturn_eval import build_blind_map, tokenize_chat
from prepare_replay_diagnostic import file_hash, new_output_directory


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("진단 사례가 비어 있습니다.")
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("중복 case_id가 있습니다.")
    for case in cases:
        if case.get("purpose") != "fixed_client_replay_diagnostic_only" or case.get("evaluation_eligible") is not False:
            raise ValueError("prepare_replay_diagnostic.py로 준비한 진단 사례만 사용하세요.")
        turns = case.get("client_turns")
        if not isinstance(turns, list) or not turns or any(not isinstance(text, str) or not text.strip() for text in turns):
            raise ValueError(f"{case['case_id']}: 내담자 발화가 비어 있습니다.")
        split = case.get("source_split")
        training_split = case.get("training_split")
        if split not in {"train", "validation", "test"} or type(training_split) is not bool or training_split != (split == "train"):
            raise ValueError("원본 분할과 학습 노출 표시가 잘못되었습니다.")
    return cases


def replay_session(
    case: dict[str, Any], generate, system_prompt: str, *, harness_version: str = "v2",
    on_turn: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if harness_version not in {"v2", "legacy"}:
        raise ValueError("harness_version은 v2 또는 legacy여야 합니다.")
    harness = CBTHarness(system_prompt, generate) if harness_version == "v2" else None
    history: list[dict[str, str]] = []
    turns: list[dict[str, Any]] = []
    for turn_index, client_text in enumerate(case["client_turns"], start=1):
        history.append({"role": "user", "content": client_text})
        if harness is not None:
            result = harness.respond(history)
        else:
            generated = generate([{"role": "system", "content": system_prompt}, *history], "response")
            if not generated.text.strip():
                raise ValueError("상담자 응답이 비어 있습니다.")
            result = {
                "response": generated.text, "generation_events": [{"purpose": "response", **asdict(generated)}],
                "warnings": [], "state": {}, "plan": {},
                "repetition_candidates": repetition_candidates(generated.text, history),
            }
        if result["state"].get("client_requested_stop") and turn_index < len(case["client_turns"]):
            result["warnings"].append("fixed_script_continues_after_stop: 진단용 원본 순서를 유지하며, 실제 대화에서는 종료해야 함")
        turn = {"turn_index": turn_index, "client_text": client_text, **result}
        turns.append(turn)
        if on_turn is not None:
            on_turn(turn)
        history.append({"role": "assistant", "content": result["response"]})
    return {
        "case_id": case["case_id"], "source_session_id": case["source_session_id"],
        "source_split": case["source_split"], "training_split": case["training_split"],
        "original_client_turn_count": case.get("original_client_turn_count", len(case["client_turns"])),
        "replayed_client_turn_count": len(case["client_turns"]),
        "client_turns_truncated": len(case["client_turns"]) < case.get("original_client_turn_count", len(case["client_turns"])),
        "purpose": "fixed_client_replay_diagnostic_only", "evaluation_eligible": False,
        "harness_version": HARNESS_VERSION if harness else "legacy-system-prompt-only",
        "messages": history, "turns": turns,
        "termination_type": "fixed_script_exhausted",
        "followup_alignment_assessed": False,
    }


def make_generator(
    model: Any, tokenizer: Any, *, disable_adapter: bool, token_limits: dict[str, int],
    response_temperature: float | None = None, response_top_p: float = 0.8,
):
    def generate(messages: list[dict[str, str]], purpose: str) -> Generation:
        import torch

        inputs = tokenize_chat(tokenizer, messages, model.device)
        limit = token_limits[purpose]
        context_limit = getattr(model.config, "max_position_embeddings", None)
        if context_limit and inputs["input_ids"].shape[-1] + limit > context_limit:
            raise ValueError("모델 문맥 상한을 초과합니다. 이력을 조용히 잘라내지 않고 중단합니다.")
        started = time.perf_counter()
        adapter_context = model.disable_adapter() if disable_adapter else nullcontext()
        sampling = {}
        if purpose == "response" and response_temperature is not None and response_temperature > 0:
            sampling = {"temperature": response_temperature, "top_p": response_top_p}
        with adapter_context, torch.inference_mode():
            output = model.generate(
                **inputs, max_new_tokens=limit, do_sample=bool(sampling), repetition_penalty=1.05,
                pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id,
                **sampling,
            )
        generated = output[0, inputs["input_ids"].shape[-1]:]
        eos_ids = tokenizer.eos_token_id
        eos_ids = set(eos_ids if isinstance(eos_ids, list) else [eos_ids])
        ended_with_eos = bool(generated.numel()) and int(generated[-1]) in eos_ids
        reason = "eos" if ended_with_eos else "length" if generated.numel() >= limit else "unknown"
        return Generation(
            text=tokenizer.decode(generated, skip_special_tokens=True).strip(),
            generated_tokens=int(generated.numel()), seconds=round(time.perf_counter() - started, 3),
            finish_reason=reason,
        )
    return generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-file", type=Path, required=True)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B")
    parser.add_argument("--harness-version", choices=["v2", "legacy"], default="v2")
    parser.add_argument("--system-prompt-file", type=Path)
    parser.add_argument("--max-response-tokens", type=int, default=384)
    parser.add_argument("--max-plan-tokens", type=int, default=768)
    parser.add_argument("--max-state-tokens", type=int, default=1536)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    cases = load_cases(args.cases_file)
    prompt_name = "system_prompt_cbt_harness_v2.txt" if args.harness_version == "v2" else "system_prompt.txt"
    prompt_path = args.system_prompt_file or Path(__file__).with_name(prompt_name)
    system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    limits = {"response": args.max_response_tokens, "plan": args.max_plan_tokens, "state": args.max_state_tokens}
    if any(limit < 1 for limit in limits.values()) or not system_prompt:
        parser.error("토큰 상한은 양수이고 시스템 프롬프트는 비어 있지 않아야 합니다.")
    if args.output_dir.exists() and (not args.output_dir.is_dir() or any(args.output_dir.iterdir())):
        parser.error("기존 결과를 덮어쓰지 않습니다. 새로운 출력 폴더를 지정하세요.")
    if not (args.adapter_path / "adapter_model.safetensors").is_file():
        parser.error("학습된 어댑터를 찾을 수 없습니다.")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise SystemExit("실제 생성에는 24GB CUDA GPU가 필요합니다. 로컬에서는 입력 준비·단위 테스트만 실행하세요.")
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer = AutoTokenizer.from_pretrained(str(args.adapter_path), use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        args.model_name, quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        ), torch_dtype=dtype, device_map={"": 0},
    )
    model = PeftModel.from_pretrained(base, str(args.adapter_path))
    model.eval()
    new_output_directory(args.output_dir)
    manifest = {
        "status": "running", "purpose": "fixed_client_replay_diagnostic_only", "evaluation_eligible": False,
        "harness_version": HARNESS_VERSION if args.harness_version == "v2" else "legacy-system-prompt-only",
        "model_name": args.model_name, "adapter_path": str(args.adapter_path),
        "conditions": {"base": "adapter disabled for every call", "tuned": "adapter enabled for every call"},
        "plan_generator": "same counselor model and adapter condition; no external model",
        "planner_visible_data": {"initial_plan": "first client utterance only", "plan_revision": "observed conversation only; no future script or reference counselor"},
        "generation": {"do_sample": False, "repetition_penalty": 1.05, "token_limits": limits, "seed": args.seed},
        "case_count": len(cases), "cases_file_sha256": file_hash(args.cases_file),
        "client_turn_counts": {case["case_id"]: len(case["client_turns"]) for case in cases},
        "truncated_case_count": sum(len(case["client_turns"]) < case.get("original_client_turn_count", len(case["client_turns"])) for case in cases),
        "system_prompt_sha256": file_hash(prompt_path),
        "source_code_sha256": {name: file_hash(Path(__file__).with_name(name)) for name in ["cbt_harness.py", "generate_replay_diagnostic.py", "generate_multiturn_eval.py", "prepare_replay_diagnostic.py"]},
        "internal_prompts": {"plan": PLAN_PROMPT, "state": STATE_PROMPT},
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "external_api_calls": 0, "runtime_crisis_filter_applied": False,
        "limitations": ["학습 분할은 학습 노출 진단용이다.", "고정 내담자는 상담자 질문에 적응하지 않는다.", "내부 진행 메모와 반복 후보는 정답이나 의미 반복 평가가 아니다.", "종료 의사가 있어도 진단용 고정 스크립트는 끝까지 재생한다. 실제 대화의 종료 정책이 아니다."],
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    blind_map = build_blind_map(cases, args.seed)
    (args.output_dir / "blind_key.json").write_text(json.dumps(blind_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        with (args.output_dir / "sessions_unblinded.jsonl").open("x", encoding="utf-8") as raw, (args.output_dir / "sessions_blinded.jsonl").open("x", encoding="utf-8") as blind, (args.output_dir / "turn_events.jsonl").open("x", encoding="utf-8") as journal:
            for case in cases:
                for condition in ("base", "tuned"):
                    def record_turn(turn: dict[str, Any]) -> None:
                        journal.write(json.dumps({"case_id": case["case_id"], "condition": condition, **turn}, ensure_ascii=False) + "\n")
                        journal.flush()
                        finish = turn["generation_events"][-1]["finish_reason"]
                        print(f"{case['case_id']} {condition} turn={turn['turn_index']} finish={finish} warnings={len(turn['warnings'])}", flush=True)

                    generate = make_generator(model, tokenizer, disable_adapter=condition == "base", token_limits=limits)
                    session = replay_session(case, generate, system_prompt, harness_version=args.harness_version, on_turn=record_turn)
                    raw.write(json.dumps({"condition": condition, **session}, ensure_ascii=False) + "\n")
                    raw.flush()
                    label = next(label for label, mapped in blind_map[case["case_id"]].items() if mapped == condition)
                    blind.write(json.dumps({
                        "case_id": case["case_id"], "model_label": label, "messages": session["messages"],
                        "purpose": session["purpose"], "evaluation_eligible": False,
                        "source_split": session["source_split"], "training_split": session["training_split"],
                        "original_client_turn_count": session["original_client_turn_count"],
                        "replayed_client_turn_count": session["replayed_client_turn_count"],
                        "client_turns_truncated": session["client_turns_truncated"],
                    }, ensure_ascii=False) + "\n")
                    blind.flush()
    except Exception as error:
        manifest.update(status="failed", error_type=type(error).__name__, error=str(error))
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    manifest.update(status="complete", finished_at_utc=datetime.now(timezone.utc).isoformat())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"진단용 생성 완료: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
