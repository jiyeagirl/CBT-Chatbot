# 실험별 파일 인덱스

동일 코드 세트는 공유하고 프롬프트·설정은 실험 폴더에 보존했다.

| ID | 실험 | 코드 세트 | 신규 세션 / 상담자 응답 |
|---|---|---|---:|
| [E00_training](E00_training/README.md) | Qwen3-8B CBT QLoRA 학습 배경 | `training_20260923` | 0 / 0 |
| [E01_initial_multiturn](E01_initial_multiturn/README.md) | Qwen 원본/CBT 파인튜닝 반응형 180세션 | `qwen_client_20261003` | 180 / 2160 |
| [E02_gpt_clients](E02_gpt_clients/README.md) | GPT 내담자 후보 비교 | `gpt_client_20261006` | 10 / 117 |
| [E03_plan_state](E03_plan_state/README.md) | 계획·상태 하네스 v2 | `qwen_replay_20261006` | 6 / 70 |
| [E04_prompt_ablation](E04_prompt_ablation/README.md) | 원본/파인튜닝 × 기본/v2 프롬프트 | `qwen_replay_20261006` | 12 / 140 |
| [E05_gpt_counselor](E05_gpt_counselor/README.md) | GPT 상담자 참고 비교 | `gpt_counselor_reference` | 1 / 14 |
| [E06_question_rules](E06_question_rules/README.md) | 질문 규칙 완화 | `qwen_replay_20261006` | 2 / 28 |
| [E07_no_reconsent](E07_no_reconsent/README.md) | 재동의·형식적 질문 마무리 방지 | `qwen_replay_20261007` | 1 / 14 |
| [E08_transition_examples](E08_transition_examples/README.md) | 전환 대화 예시 추가 | `qwen_replay_20261007` | 12 / 140 |
| [E09_gemma_qwen9b](E09_gemma_qwen9b/README.md) | Gemma 4 31B IT / Qwen3.5-9B | `candidate_initial` | 6 / 70 |
| [E10_qwen27b](E10_qwen27b/README.md) | Qwen3.5-27B 추가 | `candidate_initial` | 3 / 35 |
| [E11_mistral_exaone](E11_mistral_exaone/README.md) | Mistral Small 3.2 / EXAONE 4.0 · greedy와 sampling | `candidate_mistral_exaone` | 12 / 140 |
| [E12_llama](E12_llama/README.md) | Llama 3 / Llama 3.1 | `candidate_llama` | 6 / 70 |

E00의 0/0은 신규 생성이 아닌 학습 배경 자료라는 뜻이다.
E10과 후속 비교의 지표 파일은 기존 모델 결과도 포함할 수 있다. 신규 응답 수와 다를 수 있으므로 중복 합산하지 않는다.
