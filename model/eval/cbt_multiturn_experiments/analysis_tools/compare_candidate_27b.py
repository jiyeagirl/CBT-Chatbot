"""추가 27B 결과를 검증하고 기존 두 후보와 나란히 읽는 노트를 만든다."""

import json
from pathlib import Path

from compare_candidate_models import LABELS, validate_results


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/candidate_27b_20261007"
PREVIOUS = ROOT / "outputs/candidate_models_20261007"
NEW_LABELS = {"qwen35_27b": "Qwen3.5-27B"}


def main():
    cases, new_sessions, new_metrics = validate_results(OUTPUT, NEW_LABELS)
    old_cases, old_sessions, old_metrics = validate_results(PREVIOUS, LABELS)
    assert cases == old_cases
    assert (OUTPUT / "system_prompt.txt").read_bytes() == (PREVIOUS / "system_prompt.txt").read_bytes()
    new_manifest = json.loads((OUTPUT / "manifest.json").read_text())
    old_manifest = json.loads((PREVIOUS / "manifest.json").read_text())
    assert new_manifest["generation"] == old_manifest["generation"]
    assert new_manifest["config"]["binaries"] == old_manifest["config"]["binaries"]
    new_runtime = json.loads((OUTPUT / "runtime.json").read_text())
    old_runtime = json.loads((PREVIOUS / "runtime.json").read_text())
    assert new_runtime["binary_sha256"] == old_runtime["binary_sha256"]
    sessions = {**new_sessions, **old_sessions}
    titles = {**NEW_LABELS, **LABELS}
    metrics = new_metrics + old_metrics
    (OUTPUT / "summary.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    overview = ["# Qwen3.5-27B 추가 비교", "",
        "이번 생성: 27B 3세션·35응답. 기존 9B·Gemma 결과를 재사용해 총 9세션·105응답을 나란히 표시한다.", "",
        "동일한 고정 내담자 발화·시스템 지침·전체 이력. CBT 어댑터, 추가 예시, 상태·계획 훅 없음.", "",
        "동일 실행기·설정: GGUF Q4_0, llama.cpp b11429, temperature 0, repeat_penalty 1.05, repeat_last_n 8192, seed 42, 비사고 모드, 최대 응답 384토큰, context 8192. 모델별 내장 템플릿은 다르다.", "",
        "고정 내담자는 모델 질문에 적응하지 않는다. 원본 호전 발화는 모델의 효과가 아니다. R001은 중간 구간이며, 전체 결과는 정식 CTRS 평가가 아닌 반복·흐름 진단이다.", "",
        "## 문자열 참고 지표", "",
        "물음표 수는 질문 품질 지표가 아니며 인용 질문도 포함한다. 동일 질문 후보 수는 의미 수준의 반복을 놓칠 수 있다.", "",
        "| 모델 | 사례 | 응답 | 물음표 포함 | 동일 질문 후보 | 완전 중복 | 상한 종료 |",
        "|---|---|---:|---:|---:|---:|---:|"]
    for row in metrics:
        overview.append(f"| {row['model']} | {row['case_id']} | {row['response_count']} | {row['question_mark_turns']} | {row['repeated_question_turns']} | {row['exact_duplicate_turns']} | {row['token_cap_turns']} |")
    for case in cases:
        lines = [f"# {case['case_id']} · 27B / 9B / Gemma 비교", ""]
        for index, client in enumerate(case["client_turns"]):
            lines.extend([f"## 대화쌍 {index + 1}", "", "내담자: " + client, ""])
            for label, title in titles.items():
                turn = sessions[label, case["case_id"]]["turns"][index]
                capped = turn["generation_events"][0]["finish_reason"] == "length"
                lines.extend(["### " + title + (" · 토큰 상한 종료" if capped else ""), "", turn["response"], ""])
        (OUTPUT / f"{case['case_id']}_COMPARISON.md").write_text("\n".join(lines) + "\n")
        overview.extend(["", f"- [{case['case_id']} 전체 대화]({case['case_id']}_COMPARISON.md)"])
    (OUTPUT / "COMPARISON.md").write_text("\n".join(overview) + "\n")
    print(json.dumps(new_metrics, ensure_ascii=False, indent=2))
    print("Verified: 27B 3 sessions / 35 responses; prior 6 sessions reused unchanged.")


if __name__ == "__main__":
    main()
