#!/usr/bin/env python3
"""Base Qwen 내담자와 Base/CBT-QLoRA 상담자의 대화 180세트를 생성한다."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import time
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONDITIONS = {
    "base": "CBT harness + Qwen3-8B (adapter disabled)",
    "tuned": "CBT harness + Qwen3-8B CBT QLoRA (adapter enabled)",
}

ATTITUDES = {
    "cooperative": {
        "ko": "협조적",
        "instruction": (
            "상담 과정에 비교적 적극적으로 참여하고 질문에 구체적으로 답한다. 다만 상담자의 말에 "
            "무조건 동의하거나 한두 번의 질문만으로 갑자기 호전되지는 않는다."
        ),
    },
    "neutral": {
        "ko": "중립적",
        "instruction": (
            "질문받은 범위에서 자연스럽게 답하고 변화 가능성을 신중하게 검토한다. 충분한 근거나 "
            "경험이 생기기 전에는 확신하거나 낙관하지 않는다."
        ),
    },
    "resistant": {
        "ko": "저항적",
        "instruction": (
            "상담 효과와 변화 가능성에 회의적이며 때때로 짧게 답하거나 방어하고 핵심 주제를 피한다. "
            "상담자가 정확히 이해하고 협력적으로 접근하면 아주 조금씩 참여할 수 있지만 쉽게 낙관하거나 "
            "과제를 수락하지 않는다."
        ),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--profiles-file", type=Path, required=True)
    parser.add_argument("--profile-selection-report", type=Path, required=True)
    parser.add_argument("--system-prompt-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B")
    parser.add_argument("--max-counselor-turns", type=int, default=12)
    parser.add_argument("--min-counselor-turns", type=int, default=10)
    parser.add_argument("--counselor-max-new-tokens", type=int, default=192)
    parser.add_argument("--client-max-new-tokens", type=int, default=160)
    parser.add_argument("--seed", type=int, default=20261003)
    return parser.parse_args()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def tokenize_chat(tokenizer: Any, messages: list[dict[str, str]], device: Any) -> dict[str, Any]:
    kwargs = {
        "tokenize": True,
        "add_generation_prompt": True,
        "return_tensors": "pt",
        "return_dict": True,
    }
    try:
        inputs = tokenizer.apply_chat_template(messages, enable_thinking=False, **kwargs)
    except TypeError:
        inputs = tokenizer.apply_chat_template(messages, **kwargs)
    return {key: value.to(device) for key, value in inputs.items()}


def generate_text(
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


def transcript_text(dialogue: list[dict[str, Any]]) -> str:
    labels = {"client": "내담자", "counselor": "상담자"}
    return "\n".join(f"{labels[row['role']]}: {row['content']}" for row in dialogue)


def client_system_prompt() -> str:
    return """당신은 CBT 상담 모델 비교평가에 참여하는 가상 내담자입니다. 상담자가 아닙니다.
반드시 내담자의 입장에서만 말하고, 상담 조언이나 질문을 하지 마세요.
프로필에 없는 사건·가족·증상·과거력을 새로 만들지 마세요.
상담자의 표현을 그대로 따라 하거나 상담자가 원하는 답을 추측해 맞추지 마세요.
한 번의 공감이나 질문만으로 갑자기 호전되거나 핵심 믿음을 완전히 바꾸지 마세요.
변화는 상담자가 감정과 의미를 정확히 이해하고, 근거·대안·행동을 충분히 함께 검토했을 때만 점진적으로 표현하세요.
응답은 자연스러운 한국어 1~3문장으로 작성하세요.
오직 다음 JSON 형식만 출력하세요:
{"utterance":"내담자 발화", "end_session":false, "end_reason":""}
세션 종료는 최소 상담자 10턴 이후, 상담자가 내용을 요약하고 다음 단계나 과제를 함께 정했으며 내담자가 실제로 마칠 준비가 된 경우에만 true로 표시하세요."""


def build_client_request(
    profile: dict[str, Any],
    attitude: str,
    dialogue: list[dict[str, Any]],
    counselor_turn: int,
) -> str:
    baseline = "\n".join(f"- {text}" for text in profile["baseline_disclosures"])
    return f"""[고정 프로필]
프로필 ID: {profile['profile_id']}
상담 시작 시점의 기준 사실:
{baseline}

[상담 태도]
{ATTITUDES[attitude]['ko']}: {ATTITUDES[attitude]['instruction']}

[현재 진행]
완료된 상담자 응답 수: {counselor_turn}
지금까지의 대화:
{transcript_text(dialogue)}

마지막 상담자 발화에 내담자로서 반응하세요. 아직 공개하지 않은 기준 사실은 상담자가 적절히 물었을 때만 자연스럽게 밝히세요."""


def parse_client_response(raw_text: str) -> tuple[str, bool, str, bool]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.I | re.S)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(cleaned[start : end + 1])
            utterance = str(payload.get("utterance", "")).strip()
            if utterance:
                return (
                    utterance,
                    bool(payload.get("end_session", False)),
                    str(payload.get("end_reason", "")).strip(),
                    True,
                )
        except json.JSONDecodeError:
            pass
    fallback = cleaned.strip()
    if not fallback:
        fallback = "아직은 잘 모르겠어요. 조금 더 생각해 봐야 할 것 같아요."
    return fallback, False, "client_json_parse_fallback", False


def generate_session(
    *,
    profile: dict[str, Any],
    attitude: str,
    condition: str,
    model: Any,
    tokenizer: Any,
    counselor_system_prompt: str,
    max_turns: int,
    min_turns: int,
    counselor_max_new_tokens: int,
    client_max_new_tokens: int,
    progress: dict[str, int],
) -> dict[str, Any]:
    session_id = f"{profile['profile_id']}-{attitude}-{condition}"
    counselor_history = [{"role": "system", "content": counselor_system_prompt}]
    dialogue: list[dict[str, Any]] = [
        {"role": "client", "turn_index": 1, "content": profile["initial_utterance"]}
    ]
    generation_events: list[dict[str, Any]] = []
    termination_type = "max_turns"
    termination_reason = "maximum_counselor_turns_reached"

    for counselor_turn in range(1, max_turns + 1):
        latest_client = dialogue[-1]["content"]
        counselor_history.append({"role": "user", "content": latest_client})
        counselor_text, seconds, token_count = generate_text(
            model,
            tokenizer,
            counselor_history,
            max_new_tokens=counselor_max_new_tokens,
            disable_adapter=condition == "base",
        )
        counselor_history.append({"role": "assistant", "content": counselor_text})
        dialogue.append(
            {"role": "counselor", "turn_index": counselor_turn, "content": counselor_text}
        )
        progress["generations"] += 1
        generation_events.append(
            {
                "speaker": "counselor",
                "turn_index": counselor_turn,
                "seconds": round(seconds, 3),
                "generated_tokens": token_count,
                "adapter_disabled": condition == "base",
            }
        )
        print(
            f"GEN {progress['generations']} session={session_id} speaker=counselor "
            f"turn={counselor_turn} adapter_disabled={condition == 'base'} "
            f"seconds={seconds:.2f} tokens={token_count}",
            flush=True,
        )

        if counselor_turn == max_turns:
            break

        client_request = build_client_request(profile, attitude, dialogue, counselor_turn)
        raw_client, seconds, token_count = generate_text(
            model,
            tokenizer,
            [
                {"role": "system", "content": client_system_prompt()},
                {"role": "user", "content": client_request},
            ],
            max_new_tokens=client_max_new_tokens,
            disable_adapter=True,
        )
        client_text, requested_end, end_reason, json_valid = parse_client_response(raw_client)
        early_end_ignored = requested_end and counselor_turn < min_turns
        accepted_end = requested_end and counselor_turn >= min_turns
        dialogue.append(
            {
                "role": "client",
                "turn_index": counselor_turn + 1,
                "content": client_text,
            }
        )
        progress["generations"] += 1
        generation_events.append(
            {
                "speaker": "client",
                "turn_index": counselor_turn + 1,
                "seconds": round(seconds, 3),
                "generated_tokens": token_count,
                "adapter_disabled": True,
                "json_valid": json_valid,
                "requested_end": requested_end,
                "early_end_ignored": early_end_ignored,
            }
        )
        print(
            f"GEN {progress['generations']} session={session_id} speaker=client "
            f"turn={counselor_turn + 1} adapter_disabled=True json_valid={json_valid} "
            f"requested_end={requested_end} seconds={seconds:.2f} tokens={token_count}",
            flush=True,
        )
        if accepted_end:
            termination_type = "client_normal_end"
            termination_reason = end_reason or "client_declared_session_complete"
            break

    counselor_turn_count = sum(row["role"] == "counselor" for row in dialogue)
    client_turn_count = sum(row["role"] == "client" for row in dialogue)
    return {
        "session_id": session_id,
        "profile_id": profile["profile_id"],
        "attitude": attitude,
        "attitude_ko": ATTITUDES[attitude]["ko"],
        "condition": condition,
        "condition_description": CONDITIONS[condition],
        "source": profile["source"],
        "source_session_id": profile["source_session_id"],
        "source_stratum": profile["source_stratum"],
        "source_patterns": profile["source_patterns"],
        "counselor_turn_count": counselor_turn_count,
        "client_turn_count": client_turn_count,
        "termination_type": termination_type,
        "termination_reason": termination_reason,
        "dialogue": dialogue,
        "generation_events": generation_events,
    }


def build_blind_map(profiles: list[dict[str, Any]], seed: int) -> dict[str, dict[str, str]]:
    rng = random.Random(seed + 17)
    mapping: dict[str, dict[str, str]] = {}
    for profile in profiles:
        for attitude in ATTITUDES:
            cell_id = f"{profile['profile_id']}-{attitude}"
            labels = ["A", "B"]
            rng.shuffle(labels)
            mapping[cell_id] = {labels[0]: "base", labels[1]: "tuned"}
    return mapping


def write_outputs(
    output_dir: Path,
    profiles: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    sessions = sorted(sessions, key=lambda row: row["session_id"])
    write_jsonl(output_dir / "sessions_unblinded.jsonl", sessions)
    blind_map = build_blind_map(profiles, manifest["generation"]["seed"])
    lookup = {
        (row["profile_id"], row["attitude"], row["condition"]): row for row in sessions
    }

    blind_key_rows: list[dict[str, Any]] = []
    blinded_sessions: list[dict[str, Any]] = []
    turns_unblinded: list[dict[str, Any]] = []
    turns_blinded: list[dict[str, Any]] = []

    for session in sessions:
        for row in session["dialogue"]:
            turns_unblinded.append(
                {
                    "session_id": session["session_id"],
                    "profile_id": session["profile_id"],
                    "attitude": session["attitude"],
                    "condition": session["condition"],
                    "role": row["role"],
                    "turn_index": row["turn_index"],
                    "content": row["content"],
                }
            )

    for profile in profiles:
        profile_id = profile["profile_id"]
        for attitude in ATTITUDES:
            cell_id = f"{profile_id}-{attitude}"
            for label in ["A", "B"]:
                condition = blind_map[cell_id][label]
                session = lookup[(profile_id, attitude, condition)]
                blind_session_id = f"{cell_id}-{label}"
                blind_key_rows.append(
                    {
                        "blind_session_id": blind_session_id,
                        "profile_id": profile_id,
                        "attitude": attitude,
                        "model_label": label,
                        "condition": condition,
                        "condition_description": CONDITIONS[condition],
                    }
                )
                blinded_sessions.append(
                    {
                        "session_id": blind_session_id,
                        "profile_id": profile_id,
                        "attitude": attitude,
                        "attitude_ko": ATTITUDES[attitude]["ko"],
                        "model_label": label,
                        "counselor_turn_count": session["counselor_turn_count"],
                        "client_turn_count": session["client_turn_count"],
                        "termination_type": session["termination_type"],
                        "dialogue": session["dialogue"],
                    }
                )
                for row in session["dialogue"]:
                    turns_blinded.append(
                        {
                            "session_id": blind_session_id,
                            "profile_id": profile_id,
                            "attitude": attitude,
                            "model_label": label,
                            "role": row["role"],
                            "turn_index": row["turn_index"],
                            "content": row["content"],
                        }
                    )

    write_jsonl(output_dir / "sessions_blinded.jsonl", blinded_sessions)
    write_csv(
        output_dir / "turns_unblinded.csv",
        turns_unblinded,
        ["session_id", "profile_id", "attitude", "condition", "role", "turn_index", "content"],
    )
    write_csv(
        output_dir / "turns_blinded.csv",
        turns_blinded,
        ["session_id", "profile_id", "attitude", "model_label", "role", "turn_index", "content"],
    )
    write_csv(
        output_dir / "blind_key.csv",
        blind_key_rows,
        [
            "blind_session_id",
            "profile_id",
            "attitude",
            "model_label",
            "condition",
            "condition_description",
        ],
    )

    score_rows: list[dict[str, Any]] = []
    process_rows: list[dict[str, Any]] = []
    for row in blinded_sessions:
        common = {
            "session_id": row["session_id"],
            "profile_id": row["profile_id"],
            "attitude": row["attitude"],
            "model_label": row["model_label"],
        }
        score_rows.append(
            {
                **common,
                "understanding_0_6": "",
                "understanding_evidence": "",
                "interpersonal_effectiveness_0_6": "",
                "interpersonal_effectiveness_evidence": "",
                "collaboration_0_6": "",
                "collaboration_evidence": "",
                "guided_discovery_0_6": "",
                "guided_discovery_evidence": "",
                "key_cognition_behavior_focus_0_6": "",
                "key_cognition_behavior_focus_evidence": "",
                "change_strategy_0_6": "",
                "change_strategy_evidence": "",
                "ctrs6_total_0_36": "",
                "evaluator_id": "",
                "evaluator_model_version": "",
                "evaluation_prompt_version": "",
                "evaluation_run_index": "",
                "reviewer_notes": "",
            }
        )
        process_rows.append(
            {
                **common,
                "goal_agreement_turn": "",
                "core_cognition_or_behavior_turn": "",
                "cbt_technique_application_turn": "",
                "new_perspective_turn": "",
                "homework_agreement_turn": "",
                "summary_turn": "",
                "termination_type": row["termination_type"],
                "attitude_adherence_0_2": "",
                "profile_consistency_0_2": "",
                "unsupported_sudden_improvement_0_2": "",
                "repetition_or_loop_0_2": "",
                "notes": "",
            }
        )

    write_csv(output_dir / "ctrs6_scores_template.csv", score_rows, list(score_rows[0].keys()))
    write_csv(output_dir / "process_and_client_quality_template.csv", process_rows, list(process_rows[0].keys()))
    write_json(output_dir / "manifest.json", manifest)

    readme = """# CBT 하네스 Base Qwen vs Qwen-CBT 다중 턴 평가셋

## 설계

- held-out CACTUS-KO 프로필 30개
- 내담자 태도 3종: 협조적, 중립적, 저항적
- 상담자 조건 2종: Base Qwen, Qwen-CBT QLoRA
- 총 180세션
- 세션당 상담자 10~12턴, 내담자 10~12턴 이상
- PANAS 제외, CTRS 6항목 평가용

## 모델 역할

- AI 내담자는 모든 조건에서 Base Qwen3-8B이며 QLoRA 어댑터를 항상 비활성화했습니다.
- 상담자는 동일한 CBT 하네스와 생성 설정을 사용하고 QLoRA 활성화 여부만 다릅니다.
- 내담자는 상담자 조건과 모델명을 알지 못합니다.
- 규칙 기반 위기어 필터는 이번 일반 상담 CTRS 비교에 적용하지 않았습니다.

## 주요 파일

- `sessions_blinded.jsonl`: 자동·전문가 평가용 블라인드 세션
- `turns_blinded.csv`: 턴 단위 블라인드 대화
- `ctrs6_scores_template.csv`: CTRS 6항목 점수와 근거 입력 양식
- `process_and_client_quality_template.csv`: 목표·기법·과제 도달 턴과 내담자 품질 양식
- `blind_key.csv`: 평가 종료 후에만 열어야 하는 모델 조건 키
- `sessions_unblinded.jsonl`, `turns_unblinded.csv`: 감사용 원조건 결과
- `profiles.json`, `profile_selection_report.json`: 프로필 선정 근거
- `manifest.json`, `validation_summary.json`, `CHECKSUMS.sha256`: 재현·무결성 정보

## 해석상 제한

Base Qwen이 내담자이면서 Base 상담자 조건에도 사용되므로 같은 모델 계열의 문체 적합성이 결과에
영향을 줄 수 있습니다. 두 상담자 조건에는 동일하게 적용했으며, 최종 연구 단계에서는 일부 프로필을
다른 내담자 모델로 반복해 순위 강건성을 확인하는 것을 권장합니다.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")


def validate_outputs(
    profiles: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    min_turns: int,
    max_turns: int,
) -> dict[str, Any]:
    expected_sessions = len(profiles) * len(ATTITUDES) * len(CONDITIONS)
    session_ids = [row["session_id"] for row in sessions]
    cell_counts = Counter((row["profile_id"], row["attitude"]) for row in sessions)
    conditions_per_cell = {
        f"{profile_id}-{attitude}": sorted(
            row["condition"]
            for row in sessions
            if row["profile_id"] == profile_id and row["attitude"] == attitude
        )
        for profile_id, attitude in cell_counts
    }
    invalid_turn_counts = [
        row["session_id"]
        for row in sessions
        if not (min_turns <= row["counselor_turn_count"] <= max_turns)
    ]
    invalid_cells = [cell for cell, values in conditions_per_cell.items() if values != ["base", "tuned"]]
    client_events = [
        event
        for row in sessions
        for event in row["generation_events"]
        if event["speaker"] == "client"
    ]
    counselor_events = [
        event
        for row in sessions
        for event in row["generation_events"]
        if event["speaker"] == "counselor"
    ]
    adapter_state_errors = sum(
        event["adapter_disabled"] is not True for event in client_events
    ) + sum(
        event["adapter_disabled"] != (row["condition"] == "base")
        for row in sessions
        for event in row["generation_events"]
        if event["speaker"] == "counselor"
    )
    report = {
        "valid": True,
        "expected_session_count": expected_sessions,
        "actual_session_count": len(sessions),
        "unique_session_count": len(set(session_ids)),
        "profile_count": len(profiles),
        "attitude_counts": dict(Counter(row["attitude"] for row in sessions)),
        "condition_counts": dict(Counter(row["condition"] for row in sessions)),
        "termination_counts": dict(Counter(row["termination_type"] for row in sessions)),
        "counselor_turn_count_range": [
            min(row["counselor_turn_count"] for row in sessions),
            max(row["counselor_turn_count"] for row in sessions),
        ],
        "invalid_turn_count_sessions": invalid_turn_counts,
        "invalid_cells": invalid_cells,
        "client_json_parse_fallback_count": sum(not event.get("json_valid", True) for event in client_events),
        "early_end_ignored_count": sum(event.get("early_end_ignored", False) for event in client_events),
        "adapter_state_error_count": adapter_state_errors,
    }
    report["valid"] = all(
        [
            len(sessions) == expected_sessions,
            len(set(session_ids)) == expected_sessions,
            not invalid_turn_counts,
            not invalid_cells,
            adapter_state_errors == 0,
        ]
    )
    return report


def main() -> None:
    args = parse_args()

    import peft
    import torch
    import transformers
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise SystemExit("CUDA GPU가 필요합니다.")
    adapter_file = args.adapter_path / "adapter_model.safetensors"
    if not adapter_file.is_file():
        raise SystemExit(f"어댑터 파일을 찾을 수 없습니다: {adapter_file}")

    profiles = json.loads(args.profiles_file.read_text(encoding="utf-8"))
    if len(profiles) != 30:
        raise SystemExit(f"프로필 수가 30개가 아닙니다: {len(profiles)}")
    counselor_system_prompt = args.system_prompt_file.read_text(encoding="utf-8").strip()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "profiles.json").write_text(args.profiles_file.read_text(encoding="utf-8"), encoding="utf-8")
    (output_dir / "profile_selection_report.json").write_text(
        args.profile_selection_report.read_text(encoding="utf-8"), encoding="utf-8"
    )

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

    started_at = datetime.now(timezone.utc)
    sessions_path = output_dir / "sessions_unblinded.jsonl"
    sessions = read_jsonl(sessions_path)
    completed_ids = {row["session_id"] for row in sessions}
    progress = {
        "sessions": len(sessions),
        "generations": sum(len(row.get("generation_events", [])) for row in sessions),
    }

    for profile_index, profile in enumerate(profiles):
        for attitude_index, attitude in enumerate(ATTITUDES):
            condition_order = ["base", "tuned"]
            if (profile_index + attitude_index) % 2:
                condition_order.reverse()
            for condition in condition_order:
                session_id = f"{profile['profile_id']}-{attitude}-{condition}"
                if session_id in completed_ids:
                    print(f"SKIP completed session={session_id}", flush=True)
                    continue
                session = generate_session(
                    profile=profile,
                    attitude=attitude,
                    condition=condition,
                    model=model,
                    tokenizer=tokenizer,
                    counselor_system_prompt=counselor_system_prompt,
                    max_turns=args.max_counselor_turns,
                    min_turns=args.min_counselor_turns,
                    counselor_max_new_tokens=args.counselor_max_new_tokens,
                    client_max_new_tokens=args.client_max_new_tokens,
                    progress=progress,
                )
                sessions.append(session)
                completed_ids.add(session_id)
                progress["sessions"] += 1
                write_jsonl(sessions_path, sessions)
                write_json(
                    output_dir / "checkpoint.json",
                    {
                        "completed_sessions": progress["sessions"],
                        "expected_sessions": 180,
                        "last_session_id": session_id,
                        "generation_count": progress["generations"],
                    },
                )
                print(
                    f"SESSION {progress['sessions']}/180 completed session={session_id} "
                    f"counselor_turns={session['counselor_turn_count']} "
                    f"termination={session['termination_type']}",
                    flush=True,
                )

    finished_at = datetime.now(timezone.utc)
    device_properties = torch.cuda.get_device_properties(0)
    manifest = {
        "created_at_utc": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "model_name": args.model_name,
        "adapter_sha256": hash_file(adapter_file),
        "conditions": CONDITIONS,
        "attitudes": ATTITUDES,
        "design": {
            "profile_count": len(profiles),
            "attitude_count": len(ATTITUDES),
            "condition_count": len(CONDITIONS),
            "expected_session_count": 180,
            "minimum_counselor_turns": args.min_counselor_turns,
            "maximum_counselor_turns": args.max_counselor_turns,
            "panas_included": False,
            "ctrs6_template_included": True,
            "runtime_crisis_filter_applied": False,
            "client_model": "Qwen3-8B base with adapter disabled",
            "interactive_client": True,
        },
        "generation": {
            "seed": args.seed,
            "do_sample": False,
            "repetition_penalty": 1.05,
            "counselor_max_new_tokens": args.counselor_max_new_tokens,
            "client_max_new_tokens": args.client_max_new_tokens,
            "thinking_mode": False,
            "quantization": "4-bit NF4 double quantization",
            "compute_dtype": str(compute_dtype),
        },
        "runtime": {
            "gpu_name": torch.cuda.get_device_name(0),
            "gpu_total_memory_bytes": device_properties.total_memory,
            "torch_version": torch.__version__,
            "transformers_version": transformers.__version__,
            "peft_version": peft.__version__,
        },
        "input_hashes": {
            "profiles_file_sha256": hash_file(args.profiles_file),
            "profile_selection_report_sha256": hash_file(args.profile_selection_report),
            "system_prompt_file_sha256": hash_file(args.system_prompt_file),
        },
    }
    write_outputs(output_dir, profiles, sessions, manifest)
    validation = validate_outputs(
        profiles,
        sessions,
        args.min_counselor_turns,
        args.max_counselor_turns,
    )
    write_json(output_dir / "validation_summary.json", validation)
    if not validation["valid"]:
        raise SystemExit(f"출력 검증 실패: {json.dumps(validation, ensure_ascii=False)}")

    (output_dir / "checkpoint.json").unlink(missing_ok=True)
    checksum_targets = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    )
    (output_dir / "CHECKSUMS.sha256").write_text(
        "\n".join(f"{hash_file(path)}  {path.name}" for path in checksum_targets) + "\n",
        encoding="utf-8",
    )
    print(f"COMPLETE output_dir={output_dir.resolve()}", flush=True)


if __name__ == "__main__":
    main()
