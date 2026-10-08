# E12_llama · Llama 3 / Llama 3.1

Llama 3.1이 일부 상대적으로 나았지만 두 조건 모두 반복과 흐름 문제가 남았다.

- 신규 생성: 6세션 / 70상담자 응답.
- 대화 방식: `fixed_client_replay_prompt_only`.
- [당시 코드 세트](../../code/candidate_llama)
- [설정·출처·해시](record.json)
- [counselor.txt](prompts/counselor.txt)
- [원문 없는 문자열 집계](aggregate_metrics.json)
- [모델 revision·가중치 해시·실제 sampling](model_config.json)

CBT 추가 학습·예시·계획·메모 없음. 모델별 내장 템플릿은 다르며, 이전 NF4 결과와 실행기가 다르다.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.

## 실제 대화 결과 · 공개 승인된 CACTUS 사례

- [llama3_8b / llama3_8b / R002](results/llama3_8b_llama3_8b_R002.md)
- [llama3_8b / llama3_8b / R004](results/llama3_8b_llama3_8b_R004.md)
- [llama31_8b / llama31_8b / R002](results/llama31_8b_llama31_8b_R002.md)
- [llama31_8b / llama31_8b / R004](results/llama31_8b_llama31_8b_R004.md)
