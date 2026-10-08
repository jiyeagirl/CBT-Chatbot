#!/usr/bin/env python3
"""동일한 다중 턴 사례로 CBT 하네스 기본/QLoRA 조건을 생성한다."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONDITIONS = {
    "base": "CBT harness (Qwen3-8B, adapter disabled)",
    "tuned": "CBT harness + CBT QLoRA (adapter enabled)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--cases-file", type=Path, required=True)
    parser.add_argument("--system-prompt-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B")
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if len(rows) != 5:
        raise ValueError(f"사례 수가 5개가 아닙니다: {len(rows)}")
    for row in rows:
        if len(row["client_turns"]) != 10:
            raise ValueError(
                f"{row['case_id']}의 내담자 턴 수가 10개가 아닙니다: "
                f"{len(row['client_turns'])}"
            )
    return rows


def tokenize_chat(
    tokenizer: Any,
    messages: list[dict[str, str]],
    device: Any,
) -> dict[str, Any]:
    kwargs = {
        "tokenize": True,
        "add_generation_prompt": True,
        "return_tensors": "pt",
        "return_dict": True,
    }
    try:
        inputs = tokenizer.apply_chat_template(
            messages,
            enable_thinking=False,
            **kwargs,
        )
    except TypeError:
        inputs = tokenizer.apply_chat_template(messages, **kwargs)
    return {key: value.to(device) for key, value in inputs.items()}


def generate_response(
    model: Any,
    tokenizer: Any,
    messages: list[dict[str, str]],
    *,
    max_new_tokens: int,
    disable_adapter: bool,
) -> tuple[str, float, int]:
    import torch

    inputs = tokenize_chat(tokenizer, messages, model.device)
    adapter_context = model.disable_adapter() if disable_adapter else nullcontext()
    started = time.perf_counter()
    with adapter_context, torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    elapsed = time.perf_counter() - started
    generated = output[0, inputs["input_ids"].shape[-1] :]
    text = tokenizer.decode(generated, skip_special_tokens=True).strip()
    return text, elapsed, int(generated.numel())


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_blind_map(cases: list[dict[str, Any]], seed: int) -> dict[str, dict[str, str]]:
    randomizer = random.Random(seed)
    mapping: dict[str, dict[str, str]] = {}
    for case in cases:
        labels = ["A", "B"]
        randomizer.shuffle(labels)
        mapping[case["case_id"]] = {
            labels[0]: "base",
            labels[1]: "tuned",
        }
    return mapping


def make_session(
    case: dict[str, Any],
    condition: str,
    messages: list[dict[str, str]],
    timing_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "session_id": f"{case['case_id']}-{condition}",
        "case_id": case["case_id"],
        "case_title": case["title"],
        "condition": condition,
        "condition_description": CONDITIONS[condition],
        "source": case["source"],
        "source_session_id": case["source_session_id"],
        "stratum": case["stratum"],
        "risk_level": case["risk_level"],
        "evaluation_focus": case["evaluation_focus"],
        "messages": messages,
        "generation": timing_rows,
    }


def save_checkpoint(output_dir: Path, payload: dict[str, Any]) -> None:
    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_outputs(
    output_dir: Path,
    cases: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    blind_map: dict[str, dict[str, str]],
    manifest: dict[str, Any],
) -> None:
    session_lookup = {
        (row["case_id"], row["condition"]): row
        for row in sessions
    }
    write_jsonl(output_dir / "sessions_unblinded.jsonl", sessions)

    unblinded_turns: list[dict[str, Any]] = []
    for session in sessions:
        user_messages = [m["content"] for m in session["messages"] if m["role"] == "user"]
        assistant_messages = [m["content"] for m in session["messages"] if m["role"] == "assistant"]
        for turn_index, (user_text, assistant_text) in enumerate(
            zip(user_messages, assistant_messages, strict=True),
            start=1,
        ):
            unblinded_turns.append(
                {
                    "session_id": session["session_id"],
                    "case_id": session["case_id"],
                    "case_title": session["case_title"],
                    "condition": session["condition"],
                    "turn_index": turn_index,
                    "risk_level": session["risk_level"],
                    "client_text": user_text,
                    "counselor_text": assistant_text,
                }
            )
    write_csv(
        output_dir / "turns_unblinded.csv",
        unblinded_turns,
        [
            "session_id",
            "case_id",
            "case_title",
            "condition",
            "turn_index",
            "risk_level",
            "client_text",
            "counselor_text",
        ],
    )

    blind_key_rows: list[dict[str, str]] = []
    blinded_sessions: list[dict[str, Any]] = []
    blinded_turns: list[dict[str, Any]] = []
    for case in cases:
        case_id = case["case_id"]
        for blind_label in ["A", "B"]:
            condition = blind_map[case_id][blind_label]
            session = session_lookup[(case_id, condition)]
            blind_session_id = f"{case_id}-{blind_label}"
            blind_key_rows.append(
                {
                    "case_id": case_id,
                    "blind_label": blind_label,
                    "blind_session_id": blind_session_id,
                    "condition": condition,
                    "condition_description": CONDITIONS[condition],
                }
            )
            blinded_sessions.append(
                {
                    "session_id": blind_session_id,
                    "case_id": case_id,
                    "case_title": session["case_title"],
                    "model_label": blind_label,
                    "source": session["source"],
                    "stratum": session["stratum"],
                    "risk_level": session["risk_level"],
                    "evaluation_focus": session["evaluation_focus"],
                    "messages": session["messages"],
                }
            )
            user_messages = [m["content"] for m in session["messages"] if m["role"] == "user"]
            assistant_messages = [m["content"] for m in session["messages"] if m["role"] == "assistant"]
            for turn_index, (user_text, assistant_text) in enumerate(
                zip(user_messages, assistant_messages, strict=True),
                start=1,
            ):
                blinded_turns.append(
                    {
                        "session_id": blind_session_id,
                        "case_id": case_id,
                        "case_title": session["case_title"],
                        "model_label": blind_label,
                        "turn_index": turn_index,
                        "risk_level": session["risk_level"],
                        "client_text": user_text,
                        "counselor_text": assistant_text,
                        "turn_issue": "",
                        "turn_note": "",
                    }
                )

    write_jsonl(output_dir / "sessions_blinded.jsonl", blinded_sessions)
    write_csv(
        output_dir / "turns_blinded.csv",
        blinded_turns,
        [
            "session_id",
            "case_id",
            "case_title",
            "model_label",
            "turn_index",
            "risk_level",
            "client_text",
            "counselor_text",
            "turn_issue",
            "turn_note",
        ],
    )
    write_csv(
        output_dir / "blind_key.csv",
        blind_key_rows,
        [
            "case_id",
            "blind_label",
            "blind_session_id",
            "condition",
            "condition_description",
        ],
    )

    score_rows = []
    for row in blinded_sessions:
        score_rows.append(
            {
                "session_id": row["session_id"],
                "case_id": row["case_id"],
                "case_title": row["case_title"],
                "model_label": row["model_label"],
                "risk_level": row["risk_level"],
                "understanding_0_6": "",
                "interpersonal_effectiveness_0_6": "",
                "collaboration_0_6": "",
                "guided_discovery_0_6": "",
                "cognitive_behavioral_focus_0_6": "",
                "change_strategy_0_6": "",
                "ctrs6_total_0_36": "",
                "safety_guardrail_pass_fail": "",
                "reviewer_notes": "",
            }
        )
    write_csv(
        output_dir / "ctrs6_session_scores.csv",
        score_rows,
        list(score_rows[0].keys()),
    )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    readme = """# CBT 하네스 vs CBT 하네스+QLoRA 다중 턴 평가셋

## 구성

- 사례 5개 × 내담자 10턴 × 모델 조건 2개 = 상담자 응답 100개
- 두 조건은 같은 시스템 프롬프트, 내담자 발화, 디코딩 설정을 사용합니다.
- 유일한 모델 차이는 QLoRA 어댑터 활성화 여부입니다.
- `base`: CBT 하네스 + Qwen3-8B, 어댑터 비활성
- `tuned`: 동일 하네스 + 동일 기본 모델, CBT QLoRA 어댑터 활성

## 평가용 파일

- `sessions_blinded.jsonl`: 세션 단위 블라인드 대화록
- `turns_blinded.csv`: 턴 단위 블라인드 대화록과 메모 칸
- `ctrs6_session_scores.csv`: CTRS 6항목(각 0~6점) 세션 평가표
- `blind_key.csv`: A/B 모델 조건 해제 키. 채점이 끝날 때까지 열지 않는 것을 권장합니다.

## 감사·재현 파일

- `sessions_unblinded.jsonl`, `turns_unblinded.csv`: 원래 조건명이 포함된 결과
- `manifest.json`: 모델, 어댑터, 생성 설정, 파일 해시
- `generation.log`: RunPod 실행 로그

## 중요한 방법론 메모

내담자 발화는 두 모델에 완전히 동일하게 고정했습니다. 따라서 모델 간 차이는 비교하기 쉽지만,
내담자가 각 모델의 답변에 적응해 반응하는 자유 대화 시뮬레이션은 아닙니다. 4개 사례는 학습에
사용하지 않은 CACTUS test 세션의 첫 10개 내담자 발화를 사용했고, 1개는 한국어 위기 대응
검사용 사례입니다.

이번 비교에서는 규칙 기반 위기어 필터가 모델 응답을 대신하지 않습니다. 위기 감지·대응 능력은
두 모델의 원응답과 별도 `safety_guardrail_pass_fail` 항목으로 평가합니다.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    checksum_targets = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name not in {"CHECKSUMS.sha256", "checkpoint.json"}
    )
    checksum_lines = [f"{hash_file(path)}  {path.name}" for path in checksum_targets]
    (output_dir / "CHECKSUMS.sha256").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise SystemExit("CUDA GPU가 필요합니다.")
    if not (args.adapter_path / "adapter_model.safetensors").is_file():
        raise SystemExit(f"어댑터 파일을 찾을 수 없습니다: {args.adapter_path}")

    cases = load_cases(args.cases_file)
    system_prompt = args.system_prompt_file.read_text(encoding="utf-8").strip()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer = AutoTokenizer.from_pretrained(str(args.adapter_path), use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    base_model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        ),
        torch_dtype=compute_dtype,
        device_map={"": 0},
    )
    model = PeftModel.from_pretrained(base_model, str(args.adapter_path))
    model.eval()

    sessions: list[dict[str, Any]] = []
    total_generations = len(cases) * len(CONDITIONS) * 10
    completed_generations = 0
    started_at = datetime.now(timezone.utc)

    for case in cases:
        histories = {
            condition: [{"role": "system", "content": system_prompt}]
            for condition in CONDITIONS
        }
        timings = {condition: [] for condition in CONDITIONS}
        for turn_index, client_text in enumerate(case["client_turns"], start=1):
            for condition in ["base", "tuned"]:
                histories[condition].append({"role": "user", "content": client_text})
                response, seconds, generated_tokens = generate_response(
                    model,
                    tokenizer,
                    histories[condition],
                    max_new_tokens=args.max_new_tokens,
                    disable_adapter=condition == "base",
                )
                histories[condition].append({"role": "assistant", "content": response})
                timings[condition].append(
                    {
                        "turn_index": turn_index,
                        "seconds": round(seconds, 3),
                        "generated_tokens": generated_tokens,
                    }
                )
                completed_generations += 1
                print(
                    f"[{completed_generations}/{total_generations}] "
                    f"{case['case_id']} turn={turn_index} condition={condition} "
                    f"seconds={seconds:.2f} tokens={generated_tokens}",
                    flush=True,
                )
                save_checkpoint(
                    output_dir,
                    {
                        "completed_generations": completed_generations,
                        "total_generations": total_generations,
                        "case_id": case["case_id"],
                        "turn_index": turn_index,
                        "condition": condition,
                        "histories": histories,
                    },
                )
        for condition in ["base", "tuned"]:
            sessions.append(
                make_session(
                    case,
                    condition,
                    histories[condition],
                    timings[condition],
                )
            )

    finished_at = datetime.now(timezone.utc)
    blind_map = build_blind_map(cases, args.seed)
    manifest = {
        "created_at_utc": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "model_name": args.model_name,
        "adapter_path": str(args.adapter_path),
        "conditions": CONDITIONS,
        "design": {
            "case_count": len(cases),
            "client_turns_per_case": 10,
            "model_condition_count": 2,
            "assistant_response_count": completed_generations,
            "paired_client_turns": True,
            "runtime_crisis_filter_applied": False,
        },
        "generation": {
            "seed": args.seed,
            "max_new_tokens": args.max_new_tokens,
            "do_sample": False,
            "repetition_penalty": 1.05,
            "thinking_mode": False,
            "quantization": "4-bit NF4 double quantization",
            "compute_dtype": str(compute_dtype),
        },
        "cases_file_sha256": hash_file(args.cases_file),
        "system_prompt_file_sha256": hash_file(args.system_prompt_file),
    }
    write_outputs(output_dir, cases, sessions, blind_map, manifest)
    (output_dir / "checkpoint.json").unlink(missing_ok=True)
    print(f"완료: {output_dir.resolve()}", flush=True)


if __name__ == "__main__":
    main()
