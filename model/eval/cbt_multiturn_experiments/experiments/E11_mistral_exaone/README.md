# E11_mistral_exaone · Mistral Small 3.2 / EXAONE 4.0 · greedy와 sampling

반복·장문 조언 등이 남고 EXAONE의 52/70응답이 길이 상한으로 끝나 판단이 제한됐다.

- 신규 생성: 12세션 / 140상담자 응답.
- 대화 방식: `fixed_client_replay_prompt_only`.
- [당시 코드 세트](../../code/candidate_mistral_exaone)
- [설정·출처·해시](record.json)
- [counselor.txt](prompts/counselor.txt)
- [원문 없는 문자열 집계](aggregate_metrics.json)
- [모델 revision·가중치 해시·실제 sampling](model_config.json)

CBT 추가 학습·예시·계획·메모 없음. 모델별 내장 템플릿은 다르며, 이전 NF4 결과와 실행기가 다르다.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.

## 실제 대화 결과 · 공개 승인된 CACTUS 사례

- [mistral32_24b_greedy / mistral32_24b_greedy / R002](results/mistral32_24b_greedy_mistral32_24b_greedy_R002.md)
- [mistral32_24b_greedy / mistral32_24b_greedy / R004](results/mistral32_24b_greedy_mistral32_24b_greedy_R004.md)
- [mistral32_24b_sampled / mistral32_24b_sampled / R002](results/mistral32_24b_sampled_mistral32_24b_sampled_R002.md)
- [mistral32_24b_sampled / mistral32_24b_sampled / R004](results/mistral32_24b_sampled_mistral32_24b_sampled_R004.md)
- [exaone4_32b_greedy / exaone4_32b_greedy / R002](results/exaone4_32b_greedy_exaone4_32b_greedy_R002.md)
- [exaone4_32b_greedy / exaone4_32b_greedy / R004](results/exaone4_32b_greedy_exaone4_32b_greedy_R004.md)
- [exaone4_32b_sampled / exaone4_32b_sampled / R002](results/exaone4_32b_sampled_exaone4_32b_sampled_R002.md)
- [exaone4_32b_sampled / exaone4_32b_sampled / R004](results/exaone4_32b_sampled_exaone4_32b_sampled_R004.md)
