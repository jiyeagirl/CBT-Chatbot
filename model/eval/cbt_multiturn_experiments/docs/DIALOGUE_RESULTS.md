# 실제 대화 결과 · CACTUS 사례

정리일: 2026-10-09

원본 결과에 저장된 내담자 발화와 생성된 상담자 응답을 전체 턴 순서대로 옮겼다. 반복·오류·미완결 응답도 고치지 않았다.

내담자 발화는 한국어로 번역·정제한 CACTUS 합성 대화의 고정 입력이다. 새 상담자 응답에 적응하지 않으며, 후반의 긍정적 변화는 새 모델의 치료 효과가 아니다. 학습 노출 사례의 진단 결과로 정식 CTRS 평가가 아니다.

출처: [CACTUS 논문](https://aclanthology.org/2024.findings-emnlp.832/). AIHub R001 실제 상담 발화, 내담자 프로필, API 요청·응답 로그와 전체 데이터셋은 공개하지 않는다.

E00은 학습 배경, E01·E02는 다른 사례·대화 방식이므로 이 고정 사례 모음에 포함하지 않았다. 해당 실험은 기존 실행 기록과 집계 결과를 참고한다.

| 실험 | 실행 조건 | 사례 | 대화쌍 수 | 전체 대화 |
|---|---|---|---:|---|
| E03_plan_state | plan_state / base | R002 | 14 | [대화](../experiments/E03_plan_state/results/plan_state_base_R002.md) |
| E03_plan_state | plan_state / tuned | R002 | 14 | [대화](../experiments/E03_plan_state/results/plan_state_tuned_R002.md) |
| E03_plan_state | plan_state / base | R004 | 15 | [대화](../experiments/E03_plan_state/results/plan_state_base_R004.md) |
| E03_plan_state | plan_state / tuned | R004 | 15 | [대화](../experiments/E03_plan_state/results/plan_state_tuned_R004.md) |
| E04_prompt_ablation | original / base | R002 | 14 | [대화](../experiments/E04_prompt_ablation/results/original_base_R002.md) |
| E04_prompt_ablation | original / tuned | R002 | 14 | [대화](../experiments/E04_prompt_ablation/results/original_tuned_R002.md) |
| E04_prompt_ablation | original / base | R004 | 15 | [대화](../experiments/E04_prompt_ablation/results/original_base_R004.md) |
| E04_prompt_ablation | original / tuned | R004 | 15 | [대화](../experiments/E04_prompt_ablation/results/original_tuned_R004.md) |
| E04_prompt_ablation | v2 / base | R002 | 14 | [대화](../experiments/E04_prompt_ablation/results/v2_base_R002.md) |
| E04_prompt_ablation | v2 / tuned | R002 | 14 | [대화](../experiments/E04_prompt_ablation/results/v2_tuned_R002.md) |
| E04_prompt_ablation | v2 / base | R004 | 15 | [대화](../experiments/E04_prompt_ablation/results/v2_base_R004.md) |
| E04_prompt_ablation | v2 / tuned | R004 | 15 | [대화](../experiments/E04_prompt_ablation/results/v2_tuned_R004.md) |
| E05_gpt_counselor | gpt_luna / gpt_luna | R002 | 14 | [대화](../experiments/E05_gpt_counselor/results/gpt_luna_gpt_luna_R002.md) |
| E06_question_rules | relaxed / base | R002 | 14 | [대화](../experiments/E06_question_rules/results/relaxed_base_R002.md) |
| E06_question_rules | relaxed / tuned | R002 | 14 | [대화](../experiments/E06_question_rules/results/relaxed_tuned_R002.md) |
| E07_no_reconsent | no_reconsent / tuned | R002 | 14 | [대화](../experiments/E07_no_reconsent/results/no_reconsent_tuned_R002.md) |
| E08_transition_examples | control / base | R002 | 14 | [대화](../experiments/E08_transition_examples/results/control_base_R002.md) |
| E08_transition_examples | control / tuned | R002 | 14 | [대화](../experiments/E08_transition_examples/results/control_tuned_R002.md) |
| E08_transition_examples | control / base | R004 | 15 | [대화](../experiments/E08_transition_examples/results/control_base_R004.md) |
| E08_transition_examples | control / tuned | R004 | 15 | [대화](../experiments/E08_transition_examples/results/control_tuned_R004.md) |
| E08_transition_examples | examples / base | R002 | 14 | [대화](../experiments/E08_transition_examples/results/examples_base_R002.md) |
| E08_transition_examples | examples / tuned | R002 | 14 | [대화](../experiments/E08_transition_examples/results/examples_tuned_R002.md) |
| E08_transition_examples | examples / base | R004 | 15 | [대화](../experiments/E08_transition_examples/results/examples_base_R004.md) |
| E08_transition_examples | examples / tuned | R004 | 15 | [대화](../experiments/E08_transition_examples/results/examples_tuned_R004.md) |
| E09_gemma_qwen9b | gemma4_31b / gemma4_31b | R002 | 14 | [대화](../experiments/E09_gemma_qwen9b/results/gemma4_31b_gemma4_31b_R002.md) |
| E09_gemma_qwen9b | gemma4_31b / gemma4_31b | R004 | 15 | [대화](../experiments/E09_gemma_qwen9b/results/gemma4_31b_gemma4_31b_R004.md) |
| E09_gemma_qwen9b | qwen35_9b / qwen35_9b | R002 | 14 | [대화](../experiments/E09_gemma_qwen9b/results/qwen35_9b_qwen35_9b_R002.md) |
| E09_gemma_qwen9b | qwen35_9b / qwen35_9b | R004 | 15 | [대화](../experiments/E09_gemma_qwen9b/results/qwen35_9b_qwen35_9b_R004.md) |
| E10_qwen27b | qwen35_27b / qwen35_27b | R002 | 14 | [대화](../experiments/E10_qwen27b/results/qwen35_27b_qwen35_27b_R002.md) |
| E10_qwen27b | qwen35_27b / qwen35_27b | R004 | 15 | [대화](../experiments/E10_qwen27b/results/qwen35_27b_qwen35_27b_R004.md) |
| E11_mistral_exaone | mistral32_24b_greedy / mistral32_24b_greedy | R002 | 14 | [대화](../experiments/E11_mistral_exaone/results/mistral32_24b_greedy_mistral32_24b_greedy_R002.md) |
| E11_mistral_exaone | mistral32_24b_greedy / mistral32_24b_greedy | R004 | 15 | [대화](../experiments/E11_mistral_exaone/results/mistral32_24b_greedy_mistral32_24b_greedy_R004.md) |
| E11_mistral_exaone | mistral32_24b_sampled / mistral32_24b_sampled | R002 | 14 | [대화](../experiments/E11_mistral_exaone/results/mistral32_24b_sampled_mistral32_24b_sampled_R002.md) |
| E11_mistral_exaone | mistral32_24b_sampled / mistral32_24b_sampled | R004 | 15 | [대화](../experiments/E11_mistral_exaone/results/mistral32_24b_sampled_mistral32_24b_sampled_R004.md) |
| E11_mistral_exaone | exaone4_32b_greedy / exaone4_32b_greedy | R002 | 14 | [대화](../experiments/E11_mistral_exaone/results/exaone4_32b_greedy_exaone4_32b_greedy_R002.md) |
| E11_mistral_exaone | exaone4_32b_greedy / exaone4_32b_greedy | R004 | 15 | [대화](../experiments/E11_mistral_exaone/results/exaone4_32b_greedy_exaone4_32b_greedy_R004.md) |
| E11_mistral_exaone | exaone4_32b_sampled / exaone4_32b_sampled | R002 | 14 | [대화](../experiments/E11_mistral_exaone/results/exaone4_32b_sampled_exaone4_32b_sampled_R002.md) |
| E11_mistral_exaone | exaone4_32b_sampled / exaone4_32b_sampled | R004 | 15 | [대화](../experiments/E11_mistral_exaone/results/exaone4_32b_sampled_exaone4_32b_sampled_R004.md) |
| E12_llama | llama3_8b / llama3_8b | R002 | 14 | [대화](../experiments/E12_llama/results/llama3_8b_llama3_8b_R002.md) |
| E12_llama | llama3_8b / llama3_8b | R004 | 15 | [대화](../experiments/E12_llama/results/llama3_8b_llama3_8b_R004.md) |
| E12_llama | llama31_8b / llama31_8b | R002 | 14 | [대화](../experiments/E12_llama/results/llama31_8b_llama31_8b_R002.md) |
| E12_llama | llama31_8b / llama31_8b | R004 | 15 | [대화](../experiments/E12_llama/results/llama31_8b_llama31_8b_R004.md) |
