"""Llama 두 후보의 재생 대화를 검증하고 사례별 읽기 노트를 만든다."""

import json
from pathlib import Path

from compare_candidate_models import validate_results


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'outputs/candidate_llama_20261007'
LABELS = {
    'llama3_8b': 'Llama-3-8B-Instruct',
    'llama31_8b': 'Llama-3.1-8B-Instruct',
}


def main():
    cases, sessions, metrics = validate_results(OUTPUT, LABELS)
    (OUTPUT / 'summary.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n')
    notes = [
        '# Llama 3 / 3.1 · 비교 노트', '',
        '동일한 CBT 프롬프트 · 3사례 × 2모델 = 6세션 / 70응답.', '',
        '두 모델 모두 CBT 추가 파인튜닝 없음. 추가 예시나 상태·계획 훅 없이 같은 시스템 프롬프트를 사용하며, 각 모델 자신의 전체 대화 이력을 전달한다.', '',
        '공통: GGUF Q4_K_M, llama.cpp b11429, temperature 0, seed 42, context 8192, 응답 상한 384토큰, repeat_penalty 1.05. 모델별 내장 채팅 템플릿은 다르다.', '',
        '정식 CTRS/치료 효과 평가가 아닌 반복·대화 흐름 진단이다. 고정 내담자는 새 모델의 응답에 적응하지 않으며 원본 호전 발화는 새 모델의 효과가 아니다. R001은 짧은 중간 구간이다.', '',
        '## 참고 지표', '',
        '물음표 개수는 인용 질문도 포함하며, “궁금합니다” 같은 간접 질문은 놓친다. 동일 질문 후보는 문자열 검사일 뿐 의미 반복이나 CBT 품질 점수가 아니다. 상한 종료는 API의 finish_reason 기준이며 문장이 완결됐다는 뜻이 아니다.', '',
        '| 모델 | 사례 | 응답 | 물음표 포함 | 동일 질문 후보 | 완전 중복 | 토큰 상한 종료 |',
        '|---|---|---:|---:|---:|---:|---:|',
    ]
    for row in metrics:
        notes.append(f"| {row['model']} | {row['case_id']} | {row['response_count']} | {row['question_mark_turns']} | {row['repeated_question_turns']} | {row['exact_duplicate_turns']} | {row['token_cap_turns']} |")
    for case in cases:
        dialogue = [f"# {case['case_id']} · Llama 3 / 3.1", '']
        for index, client in enumerate(case['client_turns']):
            dialogue.extend([f'## 대화쌍 {index + 1}', '', '내담자: ' + client, ''])
            for label, title in LABELS.items():
                turn = sessions[label, case['case_id']]['turns'][index]
                capped = turn['generation_events'][0]['finish_reason'] == 'length'
                dialogue.extend(['### ' + title + (' · 토큰 상한 종료' if capped else ''), '', turn['response'], ''])
        filename = f"{case['case_id']}_COMPARISON.md"
        (OUTPUT / filename).write_text('\n'.join(dialogue) + '\n')
        notes.extend(['', f"- [{case['case_id']} 전체 대화]({filename})"])
    (OUTPUT / 'COMPARISON.md').write_text('\n'.join(notes) + '\n')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print('Verified: 6 sessions / 70 responses; original prompt, full history, one generation per turn.')


if __name__ == '__main__':
    main()
