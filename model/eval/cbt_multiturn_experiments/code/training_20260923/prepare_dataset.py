#!/usr/bin/env python3
"""CACTUS와 AIHub 상담 데이터를 Qwen3 SFT용으로 변환한다.

주요 원칙
- 원본 파일은 읽기만 한다.
- CACTUS의 intake_form/thought/cbt_plan은 학습 입력에 넣지 않는다.
- AIHub는 client_id 단위로 분할해 동일 내담자의 분할 누수를 막는다.
- 대화를 먼저 train/validation/test로 나눈 뒤 assistant 정답 단위 예시를 만든다.
- 각 SFT 예시는 conversational prompt/completion 형식으로 저장한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from collections.abc import Mapping
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_SYSTEM_PROMPT = """당신은 인지행동치료(CBT) 원칙을 활용하는 한국어 정서 지원 대화형 AI입니다. 의료인이나 실제 상담사를 대체하지 않으며 진단이나 처방을 하지 않습니다.

응답 원칙:
- 내담자의 감정과 핵심 생각을 먼저 짧고 정확하게 반영합니다.
- 비판하거나 단정하지 않고, 확인되지 않은 사실을 만들어내지 않습니다.
- 필요할 때만 CBT 질문이나 연습을 한 가지씩 제안합니다.
- 한 응답에서 질문은 하나만 합니다.
- 자살·자해 또는 즉각적인 위험이 의심되면 안전을 우선하고 전문적인 긴급 도움을 안내합니다.
- 장황한 설명보다 자연스럽고 따뜻한 한국어 대화를 우선합니다.
- 내부 사고 과정을 노출하지 않는 비사고 모드로 답합니다. /no_think"""

ROLE_MAP = {"상담사": "assistant", "내담자": "user"}
SPLITS = ("train", "validation", "test")

EMAIL_RE = re.compile(r"(?<![\w.-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
RRN_RE = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)")
PHONE_RE = re.compile(
    r"(?<!\d)(?:01[016789]|02|0[3-6][1-5])[- .]?\d{3,4}[- .]?\d{4}(?!\d)"
)


@dataclass
class NormalizedSession:
    session_id: str
    group_id: str
    source: str
    stratum: str
    messages: list[dict[str, str]]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "group_id": self.group_id,
            "source": self.source,
            "stratum": self.stratum,
            "messages": self.messages,
            "metadata": self.metadata,
        }


def read_json_array(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"최상위 JSON은 배열이어야 합니다: {path}")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"배열의 모든 원소는 객체여야 합니다: {path}")
    return value


def stable_id(prefix: str, raw_value: str) -> str:
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def redact_text(text: str, explicit_names: Iterable[str] = ()) -> tuple[str, int]:
    redacted = normalize_whitespace(str(text))
    replacements = 0

    for name in sorted({name.strip() for name in explicit_names if name.strip()}, key=len, reverse=True):
        if len(name) < 2:
            continue
        count = redacted.count(name)
        if count:
            redacted = redacted.replace(name, "내담자님")
            replacements += count

    placeholder_count = redacted.count("@NAME")
    redacted = redacted.replace("@NAME", "내담자님")
    replacements += placeholder_count

    for pattern, replacement in (
        (EMAIL_RE, "[이메일 삭제]"),
        (RRN_RE, "[주민등록번호 삭제]"),
        (PHONE_RE, "[전화번호 삭제]"),
    ):
        redacted, count = pattern.subn(replacement, redacted)
        replacements += count

    return redacted, replacements


def extract_cactus_name(intake_form: str) -> str:
    match = re.search(r"(?:^|\n)\s*이름\s*:\s*\n?\s*([^\n]+)", intake_form)
    return match.group(1).strip() if match else ""


def merge_consecutive_roles(messages: Sequence[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    merged: list[dict[str, str]] = []
    merge_count = 0
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1]["content"] = f"{merged[-1]['content']}\n{message['content']}".strip()
            merge_count += 1
        else:
            merged.append(dict(message))
    return merged, merge_count


def parse_cactus_dialogue(dialogue: str, explicit_names: Iterable[str]) -> tuple[list[dict[str, str]], dict[str, int]]:
    messages: list[dict[str, str]] = []
    counters = Counter()

    for line in str(dialogue).splitlines():
        if not line.strip():
            continue
        match = re.match(r"^(상담사|내담자)\s*:\s*(.*)$", line)
        if not match:
            counters["unparsed_lines"] += 1
            continue
        source_role, content = match.groups()
        content, replacements = redact_text(content, explicit_names)
        counters["pii_replacements"] += replacements
        if not content:
            counters["empty_messages"] += 1
            continue
        messages.append({"role": ROLE_MAP[source_role], "content": content})

    if messages and messages[0]["role"] == "assistant":
        messages.pop(0)
        counters["dropped_initial_assistant"] += 1

    messages, merge_count = merge_consecutive_roles(messages)
    counters["merged_consecutive_roles"] += merge_count

    while messages and messages[0]["role"] != "user":
        messages.pop(0)
        counters["dropped_leading_messages"] += 1
    while messages and messages[-1]["role"] != "assistant":
        messages.pop()
        counters["dropped_trailing_messages"] += 1

    return messages, dict(counters)


def normalize_cactus(
    records: Sequence[dict[str, Any]], system_prompt: str
) -> tuple[list[NormalizedSession], list[dict[str, Any]], Counter]:
    sessions: list[NormalizedSession] = []
    flags: list[dict[str, Any]] = []
    totals = Counter()

    for index, record in enumerate(records):
        session_id = f"cactus_{index:04d}"
        name = extract_cactus_name(str(record.get("intake_form", "")))
        dialogue, counters = parse_cactus_dialogue(record.get("dialogue", ""), [name])
        totals.update(counters)

        invalid = (
            len(dialogue) < 2
            or dialogue[0]["role"] != "user"
            or dialogue[-1]["role"] != "assistant"
            or any(dialogue[i]["role"] == dialogue[i - 1]["role"] for i in range(1, len(dialogue)))
        )
        if invalid:
            flags.append({"session_id": session_id, "source": "cactus", "reason": "invalid_role_sequence"})
            totals["dropped_sessions"] += 1
            continue

        if counters:
            flags.append({
                "session_id": session_id,
                "source": "cactus",
                "reason": "normalized",
                "details": counters,
            })

        technique = normalize_whitespace(str(record.get("cbt_technique", "unknown"))) or "unknown"
        attitude = normalize_whitespace(str(record.get("attitude", "unknown"))) or "unknown"
        sessions.append(
            NormalizedSession(
                session_id=session_id,
                group_id=session_id,
                source="cactus",
                stratum=technique,
                messages=[{"role": "system", "content": system_prompt}, *dialogue],
                metadata={
                    "cbt_technique": technique,
                    "patterns": list(record.get("patterns", [])),
                    "attitude": attitude,
                },
            )
        )

    return sessions, flags, totals


def normalize_aihub(
    records: Sequence[dict[str, Any]], system_prompt: str
) -> tuple[list[NormalizedSession], list[dict[str, Any]], Counter]:
    sessions: list[NormalizedSession] = []
    flags: list[dict[str, Any]] = []
    totals = Counter()

    for index, record in enumerate(records):
        meta = record.get("meta", {}) if isinstance(record.get("meta"), dict) else {}
        client_raw = str(meta.get("client_id", f"unknown-{index}"))
        group_id = stable_id("client", client_raw)
        session_id = stable_id(
            "aihub",
            f"{meta.get('source_json', '')}:{meta.get('source_record_index', index)}:{index}",
        )

        normalized: list[dict[str, str]] = []
        pii_replacements = 0
        for message in record.get("messages", []):
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "system":
                continue
            if role not in {"user", "assistant"}:
                flags.append({"session_id": session_id, "source": "aihub", "reason": "unknown_role"})
                continue
            content, replacements = redact_text(message.get("content", ""), [client_raw])
            pii_replacements += replacements
            if content:
                normalized.append({"role": role, "content": content})

        normalized, merge_count = merge_consecutive_roles(normalized)
        totals["pii_replacements"] += pii_replacements
        totals["merged_consecutive_roles"] += merge_count

        while normalized and normalized[0]["role"] != "user":
            normalized.pop(0)
            totals["dropped_leading_messages"] += 1
        while normalized and normalized[-1]["role"] != "assistant":
            normalized.pop()
            totals["dropped_trailing_messages"] += 1

        invalid = (
            len(normalized) < 2
            or normalized[0]["role"] != "user"
            or normalized[-1]["role"] != "assistant"
            or any(normalized[i]["role"] == normalized[i - 1]["role"] for i in range(1, len(normalized)))
        )
        if invalid:
            flags.append({"session_id": session_id, "source": "aihub", "reason": "invalid_role_sequence"})
            totals["dropped_sessions"] += 1
            continue

        if pii_replacements or merge_count:
            flags.append({
                "session_id": session_id,
                "source": "aihub",
                "reason": "normalized",
                "details": {
                    "pii_replacements": pii_replacements,
                    "merged_consecutive_roles": merge_count,
                },
            })

        disorder = normalize_whitespace(str(meta.get("disorder_class", "unknown"))) or "unknown"
        sessions.append(
            NormalizedSession(
                session_id=session_id,
                group_id=group_id,
                source="aihub",
                stratum=disorder,
                messages=[{"role": "system", "content": system_prompt}, *normalized],
                metadata={
                    "disorder_class": disorder,
                    "session_techniques": list(meta.get("session_techniques", [])),
                },
            )
        )

    return sessions, flags, totals


def grouped_stratified_split(
    sessions: Sequence[NormalizedSession],
    ratios: dict[str, float],
    seed: int,
) -> dict[str, list[NormalizedSession]]:
    if not math.isclose(sum(ratios.values()), 1.0, abs_tol=1e-9):
        raise ValueError("분할 비율의 합은 1이어야 합니다.")

    groups: dict[str, list[NormalizedSession]] = defaultdict(list)
    for session in sessions:
        groups[session.group_id].append(session)

    total = len(sessions)
    total_by_stratum = Counter(session.stratum for session in sessions)
    targets = {split: ratios[split] * total for split in SPLITS}
    stratum_targets = {
        split: {stratum: ratios[split] * count for stratum, count in total_by_stratum.items()}
        for split in SPLITS
    }

    rng = random.Random(seed)
    ordered_groups = list(groups.items())
    rng.shuffle(ordered_groups)
    ordered_groups.sort(key=lambda item: len(item[1]), reverse=True)

    assigned: dict[str, list[NormalizedSession]] = {split: [] for split in SPLITS}
    counts = Counter()
    stratum_counts: dict[str, Counter] = {split: Counter() for split in SPLITS}

    for _, group_sessions in ordered_groups:
        group_size = len(group_sessions)
        group_strata = Counter(session.stratum for session in group_sessions)
        candidate_scores: list[tuple[float, float, str]] = []

        for split in SPLITS:
            projected_counts = dict(counts)
            projected_counts[split] = counts[split] + group_size
            total_error = sum(
                ((projected_counts.get(name, 0) - targets[name]) / max(targets[name], 1.0)) ** 2
                for name in SPLITS
            )

            stratum_error = 0.0
            for name in SPLITS:
                for stratum, target in stratum_targets[name].items():
                    value = stratum_counts[name][stratum]
                    if name == split:
                        value += group_strata[stratum]
                    stratum_error += ((value - target) / max(target, 1.0)) ** 2

            overflow = max(0.0, projected_counts[split] - targets[split]) / max(targets[split], 1.0)
            score = total_error + 0.35 * stratum_error + 2.0 * overflow**2
            candidate_scores.append((score, rng.random(), split))

        _, _, chosen = min(candidate_scores)
        assigned[chosen].extend(group_sessions)
        counts[chosen] += group_size
        stratum_counts[chosen].update(group_strata)

    group_sets = {
        split: {session.group_id for session in split_sessions}
        for split, split_sessions in assigned.items()
    }
    for left_index, left in enumerate(SPLITS):
        for right in SPLITS[left_index + 1 :]:
            overlap = group_sets[left] & group_sets[right]
            if overlap:
                raise AssertionError(f"그룹 누수 발견: {left}/{right}: {sorted(overlap)[:3]}")

    for split in SPLITS:
        rng.shuffle(assigned[split])
    return assigned


def get_tokenizer(model_name: str):
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "토큰 검사를 하려면 transformers가 필요합니다. "
            "requirements.txt 설치 후 다시 실행하거나 --skip-token-check를 사용하세요."
        ) from exc
    return AutoTokenizer.from_pretrained(model_name, use_fast=True)


def rendered_token_count(tokenizer, messages: Sequence[dict[str, str]]) -> int:
    kwargs = {
        "tokenize": True,
        "add_generation_prompt": False,
    }
    try:
        token_ids = tokenizer.apply_chat_template(messages, enable_thinking=False, **kwargs)
    except TypeError:
        token_ids = tokenizer.apply_chat_template(messages, **kwargs)

    # Transformers 5.x may return BatchEncoding even when tokenize=True,
    # whereas 4.x commonly returns the input ID list directly.
    if isinstance(token_ids, Mapping):
        token_ids = token_ids["input_ids"]
    if token_ids and isinstance(token_ids[0], (list, tuple)):
        if len(token_ids) != 1:
            raise ValueError("단일 대화 토큰화 결과에 둘 이상의 배치가 반환되었습니다.")
        token_ids = token_ids[0]
    return len(token_ids)


def make_sft_examples(
    sessions: Sequence[NormalizedSession],
    context_pairs: int,
    max_length: int,
    tokenizer=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    if context_pairs < 1:
        raise ValueError("context_pairs는 1 이상이어야 합니다.")

    examples: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    stats = Counter()

    for session in sessions:
        system_message = session.messages[0]
        dialogue = session.messages[1:]
        target_number = 0

        for target_index, message in enumerate(dialogue):
            if message["role"] != "assistant":
                continue
            target_number += 1
            start = max(0, target_index - (2 * context_pairs - 1))
            while start < target_index and dialogue[start]["role"] != "user":
                start += 1
            prompt_dialogue = [dict(item) for item in dialogue[start:target_index]]
            completion = [dict(message)]

            if not prompt_dialogue or prompt_dialogue[-1]["role"] != "user":
                flags.append({
                    "session_id": session.session_id,
                    "source": session.source,
                    "reason": "target_without_user_prompt",
                    "target_number": target_number,
                })
                stats["dropped_examples"] += 1
                continue

            prompt = [dict(system_message), *prompt_dialogue]
            token_count = None
            if tokenizer is not None:
                combined = [*prompt, *completion]
                token_count = rendered_token_count(tokenizer, combined)
                while token_count > max_length and len(prompt) > 2:
                    # system 뒤의 가장 오래된 user/assistant 한 쌍을 제거한다.
                    remove_count = 2 if len(prompt) >= 4 else 1
                    prompt = [prompt[0], *prompt[1 + remove_count :]]
                    while len(prompt) > 1 and prompt[1]["role"] != "user":
                        prompt.pop(1)
                    combined = [*prompt, *completion]
                    token_count = rendered_token_count(tokenizer, combined)

                if token_count > max_length:
                    flags.append({
                        "session_id": session.session_id,
                        "source": session.source,
                        "reason": "example_exceeds_max_length",
                        "target_number": target_number,
                        "token_count": token_count,
                    })
                    stats["dropped_examples"] += 1
                    continue

            example_id = f"{session.session_id}_a{target_number:02d}"
            examples.append(
                {
                    "example_id": example_id,
                    "session_id": session.session_id,
                    "group_id": session.group_id,
                    "source": session.source,
                    "stratum": session.stratum,
                    "prompt": prompt,
                    "completion": completion,
                    "token_count": token_count,
                }
            )
            stats[f"examples_{session.source}"] += 1

    stats["examples_total"] = len(examples)
    return examples, flags, stats


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_summary(
    split_sessions: dict[str, list[NormalizedSession]],
    split_examples: dict[str, list[dict[str, Any]]],
    normalization_stats: dict[str, Counter],
    example_stats: dict[str, Counter],
    tokenizer_name: str | None,
    max_length: int,
    context_pairs: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "configuration": {
            "tokenizer": tokenizer_name,
            "max_length": max_length,
            "context_pairs": context_pairs,
        },
        "normalization": {
            source: dict(counter) for source, counter in normalization_stats.items()
        },
        "splits": {},
    }

    for split in SPLITS:
        sessions = split_sessions[split]
        examples = split_examples[split]
        token_counts = [row["token_count"] for row in examples if row["token_count"] is not None]
        source_sessions = Counter(session.source for session in sessions)
        source_examples = Counter(row["source"] for row in examples)
        unique_groups = {session.group_id for session in sessions}
        summary["splits"][split] = {
            "sessions": len(sessions),
            "groups": len(unique_groups),
            "sessions_by_source": dict(source_sessions),
            "examples": len(examples),
            "examples_by_source": dict(source_examples),
            "examples_stats": dict(example_stats[split]),
            "token_count": {
                "min": min(token_counts) if token_counts else None,
                "max": max(token_counts) if token_counts else None,
                "mean": round(sum(token_counts) / len(token_counts), 2) if token_counts else None,
            },
        }
    return summary


def summary_markdown(summary: dict[str, Any], flag_count: int) -> str:
    lines = [
        "# Qwen3-8B 학습 데이터 준비 결과",
        "",
        "## 설정",
        "",
        f"- 토크나이저: `{summary['configuration']['tokenizer'] or '검사 생략'}`",
        f"- 최대 길이: {summary['configuration']['max_length']:,} 토큰",
        f"- 문맥: 현재 user 발화를 포함해 최근 {summary['configuration']['context_pairs']}개 대화쌍",
        f"- 품질 플래그: {flag_count:,}건",
        "",
        "## 분할 결과",
        "",
        "| 분할 | 세션 | 그룹 | CACTUS 예시 | AIHub 예시 | 전체 예시 | 최대 토큰 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for split in SPLITS:
        item = summary["splits"][split]
        by_source = item["examples_by_source"]
        lines.append(
            f"| {split} | {item['sessions']:,} | {item['groups']:,} | "
            f"{by_source.get('cactus', 0):,} | {by_source.get('aihub', 0):,} | "
            f"{item['examples']:,} | {item['token_count']['max'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "## 해석",
            "",
            "- AIHub는 해시된 내담자 그룹 단위로 분할되어 같은 내담자가 여러 분할에 나타나지 않습니다.",
            "- CACTUS의 intake form, thought, CBT plan은 학습 메시지에 포함하지 않았습니다.",
            "- `sft/*.jsonl`은 마지막 assistant 응답만 정답으로 학습하는 prompt/completion 형식입니다.",
            "- `quality_flags.jsonl`에는 원문 대신 레코드 ID와 처리 사유만 기록됩니다.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cactus", type=Path, required=True, help="CACTUS JSON 배열")
    parser.add_argument("--aihub", type=Path, required=True, help="AIHub JSON 배열")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B")
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--context-pairs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--validation-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument(
        "--system-prompt-file",
        type=Path,
        default=Path(__file__).with_name("system_prompt.txt"),
    )
    parser.add_argument(
        "--skip-token-check",
        action="store_true",
        help="토크나이저 다운로드 없이 구조만 검사합니다. 본 학습 데이터에는 권장하지 않습니다.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ratios = {
        "train": args.train_ratio,
        "validation": args.validation_ratio,
        "test": args.test_ratio,
    }
    if not math.isclose(sum(ratios.values()), 1.0, abs_tol=1e-9):
        raise SystemExit("train/validation/test 비율의 합은 1이어야 합니다.")

    system_prompt = (
        args.system_prompt_file.read_text(encoding="utf-8").strip()
        if args.system_prompt_file.exists()
        else DEFAULT_SYSTEM_PROMPT
    )

    cactus_records = read_json_array(args.cactus)
    aihub_records = read_json_array(args.aihub)
    cactus_sessions, cactus_flags, cactus_stats = normalize_cactus(cactus_records, system_prompt)
    aihub_sessions, aihub_flags, aihub_stats = normalize_aihub(aihub_records, system_prompt)

    cactus_split = grouped_stratified_split(cactus_sessions, ratios, args.seed)
    aihub_split = grouped_stratified_split(aihub_sessions, ratios, args.seed + 1)
    split_sessions = {
        split: [*cactus_split[split], *aihub_split[split]] for split in SPLITS
    }
    rng = random.Random(args.seed)
    for sessions in split_sessions.values():
        rng.shuffle(sessions)

    tokenizer = None if args.skip_token_check else get_tokenizer(args.model_name)
    split_examples: dict[str, list[dict[str, Any]]] = {}
    all_flags = [*cactus_flags, *aihub_flags]
    example_stats: dict[str, Counter] = {}

    for split in SPLITS:
        examples, flags, stats = make_sft_examples(
            split_sessions[split],
            context_pairs=args.context_pairs,
            max_length=args.max_length,
            tokenizer=tokenizer,
        )
        split_examples[split] = examples
        example_stats[split] = stats
        all_flags.extend({**flag, "split": split} for flag in flags)

        write_jsonl(
            args.output_dir / "sessions" / f"{split}.jsonl",
            (session.to_dict() for session in split_sessions[split]),
        )
        write_jsonl(args.output_dir / "sft" / f"{split}.jsonl", examples)

    summary = build_summary(
        split_sessions=split_sessions,
        split_examples=split_examples,
        normalization_stats={"cactus": cactus_stats, "aihub": aihub_stats},
        example_stats=example_stats,
        tokenizer_name=None if args.skip_token_check else args.model_name,
        max_length=args.max_length,
        context_pairs=args.context_pairs,
    )
    write_jsonl(args.output_dir / "reports" / "quality_flags.jsonl", all_flags)
    write_json(args.output_dir / "reports" / "summary.json", summary)
    markdown = summary_markdown(summary, len(all_flags))
    report_path = args.output_dir / "reports" / "summary.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")

    print(markdown)
    print(f"완료: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
