# E08_transition_examples · 전환 대화 예시 추가

원본은 사례별 효과가 엇갈리고 파인튜닝 조건은 반복이 악화돼 예시를 채택하지 않았다.

- 신규 생성: 12세션 / 140상담자 응답.
- 대화 방식: `fixed_client_replay_prompt_only`.
- [당시 코드 세트](../../code/qwen_replay_20261007)
- [설정·출처·해시](record.json)
- [control.txt](prompts/control.txt)
- [examples.txt](prompts/examples.txt)
- [원문 없는 문자열 집계](aggregate_metrics.json)

소수 진단 조건의 관찰이며 상담 효과·CTRS 점수가 아니다.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.

## 실제 대화 결과 · 공개 승인된 CACTUS 사례

- [control / base / R002](results/control_base_R002.md)
- [control / tuned / R002](results/control_tuned_R002.md)
- [control / base / R004](results/control_base_R004.md)
- [control / tuned / R004](results/control_tuned_R004.md)
- [examples / base / R002](results/examples_base_R002.md)
- [examples / tuned / R002](results/examples_tuned_R002.md)
- [examples / base / R004](results/examples_base_R004.md)
- [examples / tuned / R004](results/examples_tuned_R004.md)
