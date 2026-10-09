# E00_training · Qwen3-8B CBT QLoRA 학습 배경

4-bit QLoRA, 1 epoch. 학습 종료와 멀티턴 상담 품질은 구분한다.

- 신규 생성: 0세션 / 0상담자 응답.
- 대화 방식: `training_context`.
- [당시 코드 세트](../../code/training_20260923)
- [설정·출처·해시](record.json)
- [training_system.txt](prompts/training_system.txt)

기존 학습 로그 기준 1,464 optimizer steps, equal 복원추출. 당시 입력 파일 해시 부재. 가중치·학습 원문 제외.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.
