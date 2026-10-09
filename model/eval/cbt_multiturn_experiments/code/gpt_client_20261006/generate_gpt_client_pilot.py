#!/usr/bin/env python3
"""GPT-6 Luna와 GPT-6.1 Sol을 AI 내담자로 비교하는 10세션 파일럿을 생성한다."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


CLIENT_MODELS = {
    "gpt-6-luna": {
        "reasoning_effort": "none",
        "input_usd_per_million": 0.10,
        "cached_input_usd_per_million": 0.01,
        "output_usd_per_million": 0.50,
    },
    "gpt-6.1-sol": {
        "reasoning_effort": "low",
        "input_usd_per_million": 2.00,
        "cached_input_usd_per_million": 0.10,
        "output_usd_per_million": 10.00,
    },
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
        "ko": "저항적·비관적",
        "instruction": (
            "상담 효과와 변화 가능성에 회의적이며 때때로 짧게 답하거나 방어하고 핵심 주제를 피한다. "
            "상담자가 정확히 이해하고 협력적으로 접근하면 아주 조금씩 참여할 수 있지만 쉽게 낙관하거나 "
            "과제를 수락하지 않는다."
        ),
    },
}

CLIENT_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "utterance": {"type": "string"},
        "end_session": {"type": "boolean"},
        "end_reason": {"type": "string"},
    },
    "required": ["utterance", "end_session", "end_reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles-file", type=Path, required=True)
    parser.add_argument("--cases-file", type=Path, required=True)
    parser.add_argument("--system-prompt-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--counselor-model-name", default="Qwen/Qwen3-8B")
    parser.add_argument(
        "--client-models",
        nargs="+",
        default=list(CLIENT_MODELS),
        choices=sorted(CLIENT_MODELS),
    )
    parser.add_argument("--max-counselor-turns", type=int, default=12)
    parser.add_argument("--min-counselor-turns", type=int, default=10)
    parser.add_argument("--counselor-max-new-tokens", type=int, default=192)
    parser.add_argument("--client-max-output-tokens", type=int, default=512)
    parser.add_argument("--max-client-retries", type=int, default=2)
    parser.add_argument("--near-duplicate-threshold", type=float, default=0.88)
    parser.add_argument("--seed", type=int, default=20261006)
    return parser.parse_args()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def normalize_for_similarity(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", text.lower())


def maximum_similarity(text: str, previous_texts: list[str]) -> float:
    normalized = normalize_for_similarity(text)
    if not normalized or not previous_texts:
        return 0.0
    return max(
        SequenceMatcher(None, normalized, normalize_for_similarity(previous)).ratio()
        for previous in previous_texts
    )


def duplicate_reason(
    text: str,
    previous_texts: list[str],
    near_duplicate_threshold: float,
) -> tuple[str | None, float]:
    normalized = normalize_for_similarity(text)
    previous_normalized = [normalize_for_similarity(previous) for previous in previous_texts]
    if normalized in previous_normalized:
        return "exact_client_repeat", 1.0
    similarity = maximum_similarity(text, previous_texts)
    if len(normalized) >= 12 and similarity >= near_duplicate_threshold:
        return "near_client_repeat", similarity
    return None, similarity


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


def generate_counselor_text(
    model: Any,
    tokenizer: Any,
    messages: list[dict[str, str]],
    max_new_tokens: int,
) -> tuple[str, float, int]:
    import torch

    inputs = tokenize_chat(tokenizer, messages, model.device)
    started = time.perf_counter()
    with torch.inference_mode():
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


def client_developer_prompt(profile: dict[str, Any], attitude: str) -> str:
    baseline = "\n".join(f"- {text}" for text in profile["baseline_disclosures"])
    return f"""당신은 CBT 상담 모델 비교평가에 참여하는 가상 내담자입니다. 상담자가 아닙니다.

[고정 프로필]
프로필 ID: {profile['profile_id']}
상담 시작 시점의 기준 사실:
{baseline}

[고정 상담 태도]
{ATTITUDES[attitude]['ko']}: {ATTITUDES[attitude]['instruction']}

[역할 규칙]
- 반드시 내담자의 입장에서만 말하고 상담 조언이나 상담자 역할의 질문을 하지 마세요.
- 프로필에 없는 사건, 관계, 증상, 과거력 또는 수치를 새로 만들지 마세요.
- 아직 말하지 않은 기준 사실은 상담자가 적절히 물었을 때만 자연스럽게 밝히세요.
- 이전에 자신이 했던 발화를 그대로 또는 거의 같은 문장으로 반복하지 마세요.
- 상담자의 표현을 그대로 따라 하거나 상담자가 원하는 답을 추측해 맞추지 마세요.
- 한 번의 공감이나 질문만으로 갑자기 호전되거나 핵심 믿음을 완전히 바꾸지 마세요.
- 변화는 감정과 의미, 근거, 대안, 행동을 충분히 함께 검토한 뒤에만 점진적으로 표현하세요.
- 실제 한국어 대화처럼 자연스럽고 간결한 1~3문장으로 답하세요.
- 상담자에게 보여줄 내담자 발화만 utterance에 넣으세요.
- 최소 상담자 10턴 이전에는 end_session을 false로 유지하세요.
"""


def build_client_messages(
    profile: dict[str, Any],
    attitude: str,
    dialogue: list[dict[str, Any]],
    counselor_turn: int,
    retry_feedback: str | None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "developer", "content": client_developer_prompt(profile, attitude)}
    ]
    for row in dialogue:
        api_role = "assistant" if row["role"] == "client" else "user"
        messages.append({"role": api_role, "content": row["content"]})
    final_instruction = (
        f"현재 완료된 상담자 응답 수는 {counselor_turn}회입니다. "
        "마지막 상담자 발화에 내담자로서 반응하세요."
    )
    if retry_feedback:
        final_instruction += f" 이전 초안은 사용할 수 없었습니다: {retry_feedback}. 새로운 내용과 표현으로 다시 답하세요."
    messages.append({"role": "developer", "content": final_instruction})
    return messages


def response_usage(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    details = getattr(usage, "input_tokens_details", None)
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        cached_input_tokens=int(getattr(details, "cached_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def request_client_turn(
    openai_client: Any,
    *,
    client_model: str,
    messages: list[dict[str, str]],
    max_output_tokens: int,
    api_attempts: int = 4,
) -> tuple[dict[str, Any], dict[str, Any]]:
    last_error: Exception | None = None
    for api_attempt in range(1, api_attempts + 1):
        started = time.perf_counter()
        try:
            response = openai_client.responses.create(
                model=client_model,
                input=messages,
                reasoning={"effort": CLIENT_MODELS[client_model]["reasoning_effort"]},
                max_output_tokens=max_output_tokens,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "cbt_client_turn",
                        "strict": True,
                        "schema": CLIENT_TURN_SCHEMA,
                    }
                },
                store=False,
            )
            payload = json.loads(response.output_text)
            usage = response_usage(response)
            return payload, {
                "request_id": getattr(response, "_request_id", None),
                "response_id": getattr(response, "id", None),
                "returned_model": getattr(response, "model", None),
                "seconds": round(time.perf_counter() - started, 3),
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "output_tokens": usage.output_tokens,
                "api_attempt": api_attempt,
            }
        except Exception as error:  # SDK 오류 유형과 무관하게 제한된 횟수만 재시도한다.
            last_error = error
            if api_attempt == api_attempts:
                break
            time.sleep(2 ** (api_attempt - 1))
    raise RuntimeError(f"OpenAI API 호출이 {api_attempts}회 실패했습니다: {last_error}") from last_error


def validate_client_payload(payload: dict[str, Any]) -> tuple[str, bool, str]:
    utterance = str(payload.get("utterance", "")).strip()
    if not utterance:
        raise ValueError("empty_utterance")
    if re.search(r"(^|\n)\s*(상담자|Counselor)\s*:", utterance, flags=re.I):
        raise ValueError("counselor_role_leak")
    return (
        utterance,
        bool(payload.get("end_session", False)),
        str(payload.get("end_reason", "")).strip(),
    )


def generate_valid_client_turn(
    openai_client: Any,
    *,
    profile: dict[str, Any],
    attitude: str,
    dialogue: list[dict[str, Any]],
    counselor_turn: int,
    client_model: str,
    max_output_tokens: int,
    max_retries: int,
    near_duplicate_threshold: float,
) -> tuple[str, bool, str, list[dict[str, Any]]]:
    previous_client_texts = [row["content"] for row in dialogue if row["role"] == "client"]
    attempts: list[dict[str, Any]] = []
    retry_feedback: str | None = None

    for generation_attempt in range(1, max_retries + 2):
        messages = build_client_messages(
            profile,
            attitude,
            dialogue,
            counselor_turn,
            retry_feedback,
        )
        payload, metadata = request_client_turn(
            openai_client,
            client_model=client_model,
            messages=messages,
            max_output_tokens=max_output_tokens,
        )
        try:
            utterance, requested_end, end_reason = validate_client_payload(payload)
            rejection_reason, similarity = duplicate_reason(
                utterance,
                previous_client_texts,
                near_duplicate_threshold,
            )
        except ValueError as error:
            utterance = str(payload.get("utterance", "")).strip()
            requested_end = False
            end_reason = ""
            rejection_reason = str(error)
            similarity = maximum_similarity(utterance, previous_client_texts)

        attempt = {
            **metadata,
            "generation_attempt": generation_attempt,
            "accepted": rejection_reason is None,
            "rejection_reason": rejection_reason or "",
            "maximum_prior_client_similarity": round(similarity, 4),
            "candidate_utterance": utterance,
        }
        attempts.append(attempt)
        if rejection_reason is None:
            return utterance, requested_end, end_reason, attempts
        retry_feedback = rejection_reason

    raise RuntimeError(
        f"내담자 발화가 {max_retries + 1}회 연속 품질 검사를 통과하지 못했습니다: {attempts[-1]}"
    )


def generate_session(
    *,
    case: dict[str, str],
    profile: dict[str, Any],
    client_model: str,
    counselor_model: Any,
    counselor_tokenizer: Any,
    counselor_system_prompt: str,
    openai_client: Any,
    max_turns: int,
    min_turns: int,
    counselor_max_new_tokens: int,
    client_max_output_tokens: int,
    max_client_retries: int,
    near_duplicate_threshold: float,
) -> dict[str, Any]:
    session_id = f"{case['case_id']}-{profile['profile_id']}-{case['attitude']}-{client_model}"
    counselor_history = [{"role": "system", "content": counselor_system_prompt}]
    dialogue: list[dict[str, Any]] = [
        {"role": "client", "turn_index": 1, "content": profile["initial_utterance"]}
    ]
    generation_events: list[dict[str, Any]] = []
    termination_type = "max_turns"
    termination_reason = "maximum_counselor_turns_reached"

    for counselor_turn in range(1, max_turns + 1):
        counselor_history.append({"role": "user", "content": dialogue[-1]["content"]})
        counselor_text, seconds, token_count = generate_counselor_text(
            counselor_model,
            counselor_tokenizer,
            counselor_history,
            counselor_max_new_tokens,
        )
        counselor_history.append({"role": "assistant", "content": counselor_text})
        dialogue.append(
            {"role": "counselor", "turn_index": counselor_turn, "content": counselor_text}
        )
        generation_events.append(
            {
                "speaker": "counselor",
                "turn_index": counselor_turn,
                "seconds": round(seconds, 3),
                "generated_tokens": token_count,
            }
        )
        print(
            f"GEN session={session_id} speaker=counselor turn={counselor_turn} "
            f"seconds={seconds:.2f} tokens={token_count}",
            flush=True,
        )

        if counselor_turn == max_turns:
            break

        client_text, requested_end, end_reason, attempts = generate_valid_client_turn(
            openai_client,
            profile=profile,
            attitude=case["attitude"],
            dialogue=dialogue,
            counselor_turn=counselor_turn,
            client_model=client_model,
            max_output_tokens=client_max_output_tokens,
            max_retries=max_client_retries,
            near_duplicate_threshold=near_duplicate_threshold,
        )
        early_end_ignored = requested_end and counselor_turn < min_turns
        accepted_end = requested_end and counselor_turn >= min_turns
        dialogue.append(
            {"role": "client", "turn_index": counselor_turn + 1, "content": client_text}
        )
        generation_events.append(
            {
                "speaker": "client",
                "turn_index": counselor_turn + 1,
                "client_model": client_model,
                "requested_end": requested_end,
                "early_end_ignored": early_end_ignored,
                "attempts": attempts,
            }
        )
        accepted_attempt = attempts[-1]
        print(
            f"GEN session={session_id} speaker=client turn={counselor_turn + 1} "
            f"model={client_model} attempts={len(attempts)} "
            f"seconds={accepted_attempt['seconds']:.2f} requested_end={requested_end}",
            flush=True,
        )
        if accepted_end:
            termination_type = "client_normal_end"
            termination_reason = end_reason or "client_declared_session_complete"
            break

    return {
        "session_id": session_id,
        "case_id": case["case_id"],
        "profile_id": profile["profile_id"],
        "attitude": case["attitude"],
        "attitude_ko": ATTITUDES[case["attitude"]]["ko"],
        "client_model": client_model,
        "client_reasoning_effort": CLIENT_MODELS[client_model]["reasoning_effort"],
        "counselor_condition": "CBT harness + Qwen3-8B base",
        "source": profile["source"],
        "source_session_id": profile["source_session_id"],
        "source_stratum": profile["source_stratum"],
        "source_patterns": profile["source_patterns"],
        "counselor_turn_count": sum(row["role"] == "counselor" for row in dialogue),
        "client_turn_count": sum(row["role"] == "client" for row in dialogue),
        "termination_type": termination_type,
        "termination_reason": termination_reason,
        "dialogue": dialogue,
        "generation_events": generation_events,
    }


def client_attempts(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        attempt
        for event in session["generation_events"]
        if event["speaker"] == "client"
        for attempt in event["attempts"]
    ]


def calculate_session_cost(session: dict[str, Any]) -> dict[str, float | int]:
    attempts = client_attempts(session)
    total_input = sum(row["input_tokens"] for row in attempts)
    total_cached = sum(row["cached_input_tokens"] for row in attempts)
    total_output = sum(row["output_tokens"] for row in attempts)
    uncached_input = max(0, total_input - total_cached)
    prices = CLIENT_MODELS[session["client_model"]]
    estimated_cost = (
        uncached_input * prices["input_usd_per_million"]
        + total_cached * prices["cached_input_usd_per_million"]
        + total_output * prices["output_usd_per_million"]
    ) / 1_000_000
    return {
        "input_tokens": total_input,
        "cached_input_tokens": total_cached,
        "output_tokens": total_output,
        "estimated_api_cost_usd": round(estimated_cost, 6),
    }


def session_quality(session: dict[str, Any], threshold: float) -> dict[str, Any]:
    client_texts = [row["content"] for row in session["dialogue"] if row["role"] == "client"]
    counselor_texts = [
        row["content"] for row in session["dialogue"] if row["role"] == "counselor"
    ]

    def repeat_metrics(texts: list[str]) -> tuple[int, int, float]:
        normalized = [normalize_for_similarity(text) for text in texts]
        exact_pairs = sum(normalized[index] == normalized[index - 1] for index in range(1, len(texts)))
        near_pairs = 0
        maximum = 0.0
        for index in range(1, len(texts)):
            similarity = SequenceMatcher(None, normalized[index], normalized[index - 1]).ratio()
            maximum = max(maximum, similarity)
            if len(normalized[index]) >= 12 and similarity >= threshold:
                near_pairs += 1
        return exact_pairs, near_pairs, maximum

    client_exact, client_near, client_max_similarity = repeat_metrics(client_texts)
    counselor_exact, counselor_near, counselor_max_similarity = repeat_metrics(counselor_texts)
    attempts = client_attempts(session)
    return {
        "session_id": session["session_id"],
        "case_id": session["case_id"],
        "client_model": session["client_model"],
        "client_adjacent_exact_repeat_count": client_exact,
        "client_adjacent_near_repeat_count": client_near,
        "client_max_adjacent_similarity": round(client_max_similarity, 4),
        "counselor_adjacent_exact_repeat_count": counselor_exact,
        "counselor_adjacent_near_repeat_count": counselor_near,
        "counselor_max_adjacent_similarity": round(counselor_max_similarity, 4),
        "client_rejected_attempt_count": sum(not row["accepted"] for row in attempts),
        **calculate_session_cost(session),
    }


def build_blind_map(cases: list[dict[str, str]], models: list[str], seed: int) -> dict[str, dict[str, str]]:
    rng = random.Random(seed + 29)
    mapping: dict[str, dict[str, str]] = {}
    for case in cases:
        labels = [chr(ord("A") + index) for index in range(len(models))]
        shuffled_models = list(models)
        rng.shuffle(shuffled_models)
        mapping[case["case_id"]] = dict(zip(labels, shuffled_models))
    return mapping


def write_outputs(
    output_dir: Path,
    cases: list[dict[str, str]],
    models: list[str],
    sessions: list[dict[str, Any]],
    manifest: dict[str, Any],
    near_duplicate_threshold: float,
) -> dict[str, Any]:
    sessions = sorted(sessions, key=lambda row: row["session_id"])
    write_jsonl(output_dir / "sessions_unblinded.jsonl", sessions)
    lookup = {(row["case_id"], row["client_model"]): row for row in sessions}
    blind_map = build_blind_map(cases, models, manifest["generation"]["seed"])
    blinded_sessions: list[dict[str, Any]] = []
    blind_key_rows: list[dict[str, Any]] = []
    turn_rows: list[dict[str, Any]] = []

    for case in cases:
        for label, client_model in blind_map[case["case_id"]].items():
            session = lookup[(case["case_id"], client_model)]
            blind_session_id = f"{case['case_id']}-{label}"
            blind_key_rows.append(
                {
                    "blind_session_id": blind_session_id,
                    "case_id": case["case_id"],
                    "model_label": label,
                    "client_model": client_model,
                    "reasoning_effort": CLIENT_MODELS[client_model]["reasoning_effort"],
                }
            )
            blinded_sessions.append(
                {
                    "session_id": blind_session_id,
                    "case_id": case["case_id"],
                    "profile_id": session["profile_id"],
                    "attitude": session["attitude"],
                    "model_label": label,
                    "counselor_condition": session["counselor_condition"],
                    "termination_type": session["termination_type"],
                    "dialogue": session["dialogue"],
                }
            )
            for row in session["dialogue"]:
                turn_rows.append(
                    {
                        "session_id": blind_session_id,
                        "case_id": case["case_id"],
                        "profile_id": session["profile_id"],
                        "attitude": session["attitude"],
                        "model_label": label,
                        "role": row["role"],
                        "turn_index": row["turn_index"],
                        "content": row["content"],
                    }
                )

    write_jsonl(output_dir / "sessions_blinded.jsonl", blinded_sessions)
    write_csv(
        output_dir / "turns_blinded.csv",
        turn_rows,
        ["session_id", "case_id", "profile_id", "attitude", "model_label", "role", "turn_index", "content"],
    )
    write_csv(
        output_dir / "blind_key.csv",
        blind_key_rows,
        ["blind_session_id", "case_id", "model_label", "client_model", "reasoning_effort"],
    )

    review_rows = []
    for case in cases:
        review_rows.append(
            {
                "case_id": case["case_id"],
                "profile_id": case["profile_id"],
                "attitude": case["attitude"],
                "preferred_model_label": "",
                "naturalness_A_1_5": "",
                "naturalness_B_1_5": "",
                "profile_consistency_A_1_5": "",
                "profile_consistency_B_1_5": "",
                "attitude_adherence_A_1_5": "",
                "attitude_adherence_B_1_5": "",
                "disclosure_pacing_A_1_5": "",
                "disclosure_pacing_B_1_5": "",
                "unrealistic_improvement_A_0_1": "",
                "unrealistic_improvement_B_0_1": "",
                "reviewer_notes": "",
            }
        )
    write_csv(output_dir / "paired_review_template.csv", review_rows, list(review_rows[0]))

    quality_rows = [session_quality(session, near_duplicate_threshold) for session in sessions]
    write_csv(output_dir / "automatic_quality_audit.csv", quality_rows, list(quality_rows[0]))
    model_summary: dict[str, Any] = {}
    for client_model in models:
        rows = [row for row in quality_rows if row["client_model"] == client_model]
        model_summary[client_model] = {
            "session_count": len(rows),
            "client_adjacent_exact_repeat_total": sum(
                row["client_adjacent_exact_repeat_count"] for row in rows
            ),
            "client_adjacent_near_repeat_total": sum(
                row["client_adjacent_near_repeat_count"] for row in rows
            ),
            "client_rejected_attempt_total": sum(row["client_rejected_attempt_count"] for row in rows),
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "cached_input_tokens": sum(row["cached_input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "estimated_api_cost_usd": round(
                sum(row["estimated_api_cost_usd"] for row in rows), 6
            ),
        }
    summary = {
        "models": model_summary,
        "total_estimated_api_cost_usd": round(
            sum(row["estimated_api_cost_usd"] for row in quality_rows), 6
        ),
    }
    write_json(output_dir / "model_comparison_summary.json", summary)
    write_json(output_dir / "manifest.json", manifest)

    readme = """# GPT AI 내담자 모델 파일럿

## 목적

동일한 CBT 하네스 + Qwen3-8B Base 상담자에 대해 GPT-6 Luna와 GPT-6.1 Sol 중 어느 모델이
한국어 AI 내담자 역할에 더 적합한지 비교합니다.

## 설계

- 동일한 프로필·태도 조합 5개
- AI 내담자 2종: GPT-6 Luna, GPT-6.1 Sol
- 총 10세션
- 세션당 상담자 최대 12턴
- 상담자 모델과 생성 설정은 모든 세션에서 동일
- 내담자의 정확·근접 반복은 자동 거절하고 최대 2회 재생성

## 먼저 볼 파일

- `turns_blinded.csv`: 모델명을 가린 턴 단위 대화
- `paired_review_template.csv`: 5개 쌍의 사람 평가 양식
- `automatic_quality_audit.csv`: 반복 및 API 사용량 자동 점검
- `model_comparison_summary.json`: 모델별 반복·비용 합계
- `blind_key.csv`: 블라인드 평가가 끝난 뒤 확인할 모델 키
- `sessions_unblinded.jsonl`: 생성 메타데이터와 API 요청 기록을 포함한 감사용 원본

## 주의

이 파일럿은 CTRS 상담자 성능 비교가 아니라 AI 내담자 시뮬레이터 선택용입니다.
CTRS 점수로 두 GPT 모델을 고르지 말고, 자연스러움·프로필 일관성·태도 유지·정보 공개 속도·
과도한 호전 여부를 우선 확인하세요.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return summary


def validate_inputs(
    profiles: list[dict[str, Any]],
    cases: list[dict[str, str]],
    client_models: list[str],
) -> dict[str, dict[str, Any]]:
    profiles_by_id = {profile["profile_id"]: profile for profile in profiles}
    if len(cases) != 5:
        raise SystemExit(f"파일럿 사례 수는 정확히 5개여야 합니다: {len(cases)}")
    if len({case["case_id"] for case in cases}) != len(cases):
        raise SystemExit("case_id가 중복되었습니다.")
    for case in cases:
        if case["profile_id"] not in profiles_by_id:
            raise SystemExit(f"프로필을 찾을 수 없습니다: {case['profile_id']}")
        if case["attitude"] not in ATTITUDES:
            raise SystemExit(f"지원하지 않는 태도입니다: {case['attitude']}")
    if len(client_models) != 2 or len(set(client_models)) != 2:
        raise SystemExit("비교 가능한 서로 다른 내담자 모델 2개가 필요합니다.")
    return profiles_by_id


def main() -> None:
    args = parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY 환경변수가 필요합니다.")

    import openai
    import torch
    import transformers
    from openai import OpenAI
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise SystemExit("CUDA GPU가 필요합니다.")

    profiles = json.loads(args.profiles_file.read_text(encoding="utf-8"))
    cases = json.loads(args.cases_file.read_text(encoding="utf-8"))
    profiles_by_id = validate_inputs(profiles, cases, args.client_models)
    counselor_system_prompt = args.system_prompt_file.read_text(encoding="utf-8").strip()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "profiles_used.json").write_text(
        json.dumps(
            [profiles_by_id[case["profile_id"]] for case in cases],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "cases.json").write_text(args.cases_file.read_text(encoding="utf-8"), encoding="utf-8")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer = AutoTokenizer.from_pretrained(args.counselor_model_name, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    counselor_model = AutoModelForCausalLM.from_pretrained(
        args.counselor_model_name,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        ),
        torch_dtype=compute_dtype,
        device_map={"": 0},
    )
    counselor_model.eval()
    openai_client = OpenAI(max_retries=0, timeout=120.0)

    sessions_path = args.output_dir / "sessions_unblinded.jsonl"
    sessions = read_jsonl(sessions_path)
    completed_ids = {row["session_id"] for row in sessions}
    failures_path = args.output_dir / "failures.jsonl"
    failures = read_jsonl(failures_path)
    expected_session_count = len(cases) * len(args.client_models)
    started_at = datetime.now(timezone.utc)

    for case_index, case in enumerate(cases):
        model_order = list(args.client_models)
        if case_index % 2:
            model_order.reverse()
        for client_model in model_order:
            profile = profiles_by_id[case["profile_id"]]
            session_id = f"{case['case_id']}-{profile['profile_id']}-{case['attitude']}-{client_model}"
            if session_id in completed_ids:
                print(f"SKIP completed session={session_id}", flush=True)
                continue
            try:
                session = generate_session(
                    case=case,
                    profile=profile,
                    client_model=client_model,
                    counselor_model=counselor_model,
                    counselor_tokenizer=tokenizer,
                    counselor_system_prompt=counselor_system_prompt,
                    openai_client=openai_client,
                    max_turns=args.max_counselor_turns,
                    min_turns=args.min_counselor_turns,
                    counselor_max_new_tokens=args.counselor_max_new_tokens,
                    client_max_output_tokens=args.client_max_output_tokens,
                    max_client_retries=args.max_client_retries,
                    near_duplicate_threshold=args.near_duplicate_threshold,
                )
            except Exception as error:
                failures.append(
                    {
                        "session_id": session_id,
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )
                write_jsonl(failures_path, failures)
                raise
            sessions.append(session)
            completed_ids.add(session_id)
            write_jsonl(sessions_path, sessions)
            write_json(
                args.output_dir / "checkpoint.json",
                {
                    "completed_sessions": len(sessions),
                    "expected_sessions": expected_session_count,
                    "last_session_id": session_id,
                },
            )
            print(
                f"SESSION {len(sessions)}/{expected_session_count} completed session={session_id}",
                flush=True,
            )

    finished_at = datetime.now(timezone.utc)
    manifest = {
        "created_at_utc": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "purpose": "AI client model selection pilot; not a counselor CTRS comparison",
        "client_models": {
            model: {
                "reasoning_effort": CLIENT_MODELS[model]["reasoning_effort"],
                "pricing_per_million_tokens_usd": {
                    "input": CLIENT_MODELS[model]["input_usd_per_million"],
                    "cached_input": CLIENT_MODELS[model]["cached_input_usd_per_million"],
                    "output": CLIENT_MODELS[model]["output_usd_per_million"],
                },
            }
            for model in args.client_models
        },
        "counselor": {
            "model": args.counselor_model_name,
            "condition": "CBT harness + base model; no QLoRA adapter",
            "do_sample": False,
            "repetition_penalty": 1.05,
            "max_new_tokens": args.counselor_max_new_tokens,
        },
        "design": {
            "case_count": len(cases),
            "client_model_count": len(args.client_models),
            "expected_session_count": expected_session_count,
            "minimum_counselor_turns": args.min_counselor_turns,
            "maximum_counselor_turns": args.max_counselor_turns,
            "runtime_crisis_filter_applied": False,
        },
        "generation": {
            "seed": args.seed,
            "client_max_output_tokens": args.client_max_output_tokens,
            "max_client_retries": args.max_client_retries,
            "near_duplicate_threshold": args.near_duplicate_threshold,
            "openai_store": False,
            "structured_output": True,
        },
        "runtime": {
            "gpu_name": torch.cuda.get_device_name(0),
            "torch_version": torch.__version__,
            "transformers_version": transformers.__version__,
            "openai_version": openai.__version__,
        },
        "input_hashes": {
            "profiles_file_sha256": hash_file(args.profiles_file),
            "cases_file_sha256": hash_file(args.cases_file),
            "system_prompt_file_sha256": hash_file(args.system_prompt_file),
        },
    }
    summary = write_outputs(
        args.output_dir,
        cases,
        args.client_models,
        sessions,
        manifest,
        args.near_duplicate_threshold,
    )

    quality_rows = [session_quality(session, args.near_duplicate_threshold) for session in sessions]
    validation = {
        "valid": len(sessions) == expected_session_count
        and len({row["session_id"] for row in sessions}) == expected_session_count
        and all(row["client_adjacent_exact_repeat_count"] == 0 for row in quality_rows)
        and all(row["client_adjacent_near_repeat_count"] == 0 for row in quality_rows),
        "expected_session_count": expected_session_count,
        "actual_session_count": len(sessions),
        "unique_session_count": len({row["session_id"] for row in sessions}),
        "client_model_counts": dict(Counter(row["client_model"] for row in sessions)),
        "attitude_counts": dict(Counter(row["attitude"] for row in sessions)),
        "termination_counts": dict(Counter(row["termination_type"] for row in sessions)),
        "client_adjacent_exact_repeat_total": sum(
            row["client_adjacent_exact_repeat_count"] for row in quality_rows
        ),
        "client_adjacent_near_repeat_total": sum(
            row["client_adjacent_near_repeat_count"] for row in quality_rows
        ),
        "total_estimated_api_cost_usd": summary["total_estimated_api_cost_usd"],
    }
    write_json(args.output_dir / "validation_summary.json", validation)
    if not validation["valid"]:
        raise SystemExit(f"출력 검증 실패: {json.dumps(validation, ensure_ascii=False)}")

    (args.output_dir / "checkpoint.json").unlink(missing_ok=True)
    checksum_targets = sorted(
        path
        for path in args.output_dir.iterdir()
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    )
    (args.output_dir / "CHECKSUMS.sha256").write_text(
        "\n".join(f"{hash_file(path)}  {path.name}" for path in checksum_targets) + "\n",
        encoding="utf-8",
    )
    print(f"COMPLETE output_dir={args.output_dir.resolve()}", flush=True)
    print(f"ESTIMATED_API_COST_USD={summary['total_estimated_api_cost_usd']}", flush=True)


if __name__ == "__main__":
    main()
