"""Validate and summarize the matched prompt × adapter replay experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_replay_diagnostic import audit, read_jsonl
from prepare_replay_diagnostic import file_hash


CONDITIONS = {"original": {"base": "A", "tuned": "B"}, "v2": {"base": "C", "tuned": "D"}}
METRICS = (
    "counselor_turns", "literal_duplicate_turns", "normalized_duplicate_turns",
    "similarity_ge_0_9_candidate_turns", "repeated_question_candidate_turns",
    "response_tokens_le_10_turns", "response_length_cap_turns",
)


def review_experiment(results: Path, cases: Path, prompt_directory: Path) -> tuple[dict, str]:
    summaries = {}
    manifests = {}
    rows = []
    transcripts = ["# 4조건 대화록", "", "A=Base/기본, B=CBT/기본, C=Base/v2, D=CBT/v2. 모든 조건은 계획·상태 호출 없음.", ""]
    for variant, labels in CONDITIONS.items():
        directory = results / variant
        summaries[variant], transcript = audit(directory, cases)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifests[variant] = manifest
        prompt_name = "system_prompt.txt" if variant == "original" else "system_prompt_cbt_harness_v2.txt"
        if manifest["system_prompt_sha256"] != file_hash(prompt_directory / prompt_name):
            raise ValueError(f"{variant}: prompt checksum mismatch")
        if manifest["harness_version"] != "legacy-system-prompt-only":
            raise ValueError("Planning/state must be disabled in this ablation")
        if manifest["external_api_calls"] != 0:
            raise ValueError("Unexpected external model calls")
        for event in read_jsonl(directory / "turn_events.jsonl"):
            if len(event["generation_events"]) != 1 or event["generation_events"][0].get("purpose") != "response":
                raise ValueError("Unexpected planning/state/retry generation")
        for row in summaries[variant]["sessions"]:
            rows.append({"label": labels[row["condition"]], "prompt_variant": variant, **row})
        transcripts.extend([f"## 프롬프트: {variant}", "", transcript, ""])

    for field in ("model_name", "adapter_path", "generation", "cases_file_sha256", "client_turn_counts", "source_code_sha256"):
        if manifests["original"][field] != manifests["v2"][field]:
            raise ValueError(f"Uncontrolled experiment difference: {field}")

    totals = []
    for label in "ABCD":
        condition_rows = [row for row in rows if row["label"] == label]
        totals.append({"label": label, "session_count": len(condition_rows),
                       **{metric: sum(row[metric] for row in condition_rows) for metric in METRICS}})
    return {
        "status": "complete", "condition_labels": CONDITIONS,
        "session_count": sum(row["session_count"] for row in totals),
        "counselor_turn_count": sum(row["counselor_turns"] for row in totals),
        "matched_controls_verified": True, "planning_state_or_retry_calls": 0,
        "totals": totals, "sessions": rows,
        "definitions": summaries["original"]["definitions"],
        "limitations": ["학습 노출 3사례의 고정 입력 진단이며 정식 CTRS 평가가 아니다.",
                        "고정 내담자는 새 상담 응답에 적응하지 않는다.",
                        "문자열 반복 후보는 의미 반복이나 임상 품질의 자동 점수가 아니다.",
                        "후속 입력에는 조건별 생성 이력이 누적된다. 직접 효과와 이력 누적 효과를 모두 포함한다."],
    }, "\n".join(transcripts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--prompt-directory", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    summary, transcript = review_experiment(args.results, args.cases, args.prompt_directory)
    for name, content in (("ablation_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n"),
                          ("DIALOGUES_12_SESSIONS.md", transcript)):
        with (args.results / name).open("x", encoding="utf-8") as handle:
            handle.write(content)
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
