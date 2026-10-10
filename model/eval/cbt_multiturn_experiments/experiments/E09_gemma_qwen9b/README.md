# E09_gemma_qwen9b · Gemma 4 31B IT / Qwen3.5-9B

비질문 반영과 CBT 개입의 균형이 모델마다 달랐고 의미상 반복은 남았다.

- 신규 생성: 6세션 / 70상담자 응답.
- 대화 방식: `fixed_client_replay_prompt_only`.
- [당시 코드 세트](../../code/candidate_initial)
- [설정·출처·해시](record.json)
- [counselor.txt](prompts/counselor.txt)
- [원문 없는 문자열 집계](aggregate_metrics.json)
- [모델 revision·가중치 해시·실제 sampling](model_config.json)

CBT 추가 학습·예시·계획·메모 없음. 모델별 내장 템플릿은 다르며, 이전 NF4 결과와 실행기가 다르다.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.

## 실제 대화 결과 · 공개 승인된 CACTUS 사례

- [gemma4_31b / gemma4_31b / R002](results/gemma4_31b_gemma4_31b_R002.md)
- [gemma4_31b / gemma4_31b / R004](results/gemma4_31b_gemma4_31b_R004.md)
- [qwen35_9b / qwen35_9b / R002](results/qwen35_9b_qwen35_9b_R002.md)
- [qwen35_9b / qwen35_9b / R004](results/qwen35_9b_qwen35_9b_R004.md)
