"""Mistral·EXAONE의 고정 발화 재생 결과를 검증하고 읽기용 노트를 만든다."""

import json
from pathlib import Path

from compare_candidate_models import validate_results


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/candidate_mistral_exaone_20261007"
LABELS = {
    "mistral32_24b_greedy": "Mistral 3.2 24B · greedy",
    "mistral32_24b_sampled": "Mistral 3.2 24B · temp 0.15",
    "exaone4_32b_greedy": "EXAONE 4.0 32B · greedy",
    "exaone4_32b_sampled": "EXAONE 4.0 32B · temp 0.3",
}


def main():
    cases, sessions, metrics = validate_results(OUTPUT, LABELS)
    (OUTPUT / "summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    overview = [
        "# Mistral · EXAONE 비교 노트", "",
        "2모델 × 생성 설정 2종 × 고정 내담자 사례 3개 = 12세션·140응답.", "",
        "동일한 CBT 시스템 지침과 각 모델 자신의 전체 응답 이력을 사용한다. 어댑터, 추가 예시, 상태·계획 훅은 없다.", "",
        "공통: GGUF Q4_K_M, llama.cpp b11429, context 8192, 최대 응답 384토큰, seed 42, repeat_penalty 1.05, repeat_last_n 8192, 비사고 모드. top_p=1, top_k=0, min_p=0. 모델별 내장 채팅 템플릿은 다르다.", "",
        "greedy는 temperature=0. 샘플링은 Mistral 0.15, EXAONE 0.3으로 설정했다. EXAONE 0.3은 공식 비사고 모드 권장 범위(<0.6) 안에서 선택한 값이다. 각 설정 1회 실행이므로 샘플링 분산은 평가하지 않았다.", "",
        "고정 내담자는 새 상담자 질문에 적응하지 않는다. 원본의 호전 발화는 새 모델의 효과가 아니다. R001은 중간 구간이며, 이 실험은 정식 CTRS 평가나 임상 효과 검증이 아닌 반복·대화 흐름 진단이다.", "",
        "이전 Qwen·Gemma 결과는 Q4_0이므로 이번 결과와 양자화까지 통제한 직접 비교는 아니다.", "",
        "## 문자열 참고 지표", "",
        "물음표는 인용 질문도 포함하며 질문 품질을 뜻하지 않는다. 완전 중복이 없어도 의미 수준의 반복은 있을 수 있다.", "",
        "| 모델·설정 | 사례 | 응답 | 물음표 포함 | 동일 질문 후보 | 완전 중복 | 상한 종료 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in metrics:
        overview.append(
            f"| {row['model']} | {row['case_id']} | {row['response_count']} | "
            f"{row['question_mark_turns']} | {row['repeated_question_turns']} | "
            f"{row['exact_duplicate_turns']} | {row['token_cap_turns']} |")
    for case in cases:
        lines = [f"# {case['case_id']} · Mistral / EXAONE", ""]
        for index, client in enumerate(case["client_turns"]):
            lines.extend([f"## 대화쌍 {index + 1}", "", "내담자: " + client, ""])
            for label, title in LABELS.items():
                turn = sessions[label, case["case_id"]]["turns"][index]
                capped = turn["generation_events"][0]["finish_reason"] == "length"
                lines.extend(["### " + title + (" · 토큰 상한 종료" if capped else ""),
                              "", turn["response"], ""])
        filename = f"{case['case_id']}_COMPARISON.md"
        (OUTPUT / filename).write_text("\n".join(lines) + "\n")
        overview.extend(["", f"- [{case['case_id']} 전체 대화]({filename})"])
    (OUTPUT / "COMPARISON.md").write_text("\n".join(overview) + "\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("Verified: 12 sessions / 140 responses.")


if __name__ == "__main__":
    main()
