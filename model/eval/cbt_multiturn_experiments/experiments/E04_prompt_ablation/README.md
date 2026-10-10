# E04_prompt_ablation · 원본/파인튜닝 × 기본/v2 프롬프트

계획·상태 없이도 반복. 프롬프트 효과가 원본과 파인튜닝 조건에서 다르게 나타났다.

- 신규 생성: 12세션 / 140상담자 응답.
- 대화 방식: `fixed_client_replay_prompt_only`.
- [당시 코드 세트](../../code/qwen_replay_20261006)
- [설정·출처·해시](record.json)
- [original.txt](prompts/original.txt)
- [v2.txt](prompts/v2.txt)
- [원문 없는 문자열 집계](aggregate_metrics.json)

소수 진단 조건의 관찰이며 상담 효과·CTRS 점수가 아니다.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.

## 실제 대화 결과 · 공개 승인된 CACTUS 사례

- [original / base / R002](results/original_base_R002.md)
- [original / tuned / R002](results/original_tuned_R002.md)
- [original / base / R004](results/original_base_R004.md)
- [original / tuned / R004](results/original_tuned_R004.md)
- [v2 / base / R002](results/v2_base_R002.md)
- [v2 / tuned / R002](results/v2_tuned_R002.md)
- [v2 / base / R004](results/v2_base_R004.md)
- [v2 / tuned / R004](results/v2_tuned_R004.md)
