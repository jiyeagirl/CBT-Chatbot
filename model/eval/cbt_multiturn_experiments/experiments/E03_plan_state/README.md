# E03_plan_state · 계획·상태 하네스 v2

반복이 남았고 계획·진행 메모의 파싱/검증 오류가 자주 발생했다.

- 신규 생성: 6세션 / 70상담자 응답.
- 대화 방식: `fixed_client_replay_plan_state`.
- [당시 코드 세트](../../code/qwen_replay_20261006)
- [설정·출처·해시](record.json)
- [v2.txt](prompts/v2.txt)
- [원문 없는 문자열 집계](aggregate_metrics.json)

메모 실패: 원본 33/35, 파인튜닝 35/35. legacy 대조군 없이 v2 효과를 확정하지 않는다.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.

## 실제 대화 결과 · 공개 승인된 CACTUS 사례

- [plan_state / base / R002](results/plan_state_base_R002.md)
- [plan_state / tuned / R002](results/plan_state_tuned_R002.md)
- [plan_state / base / R004](results/plan_state_base_R004.md)
- [plan_state / tuned / R004](results/plan_state_tuned_R004.md)
