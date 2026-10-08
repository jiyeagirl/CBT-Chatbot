# E02_gpt_clients · GPT 내담자 후보 비교

내담자 반응은 다양해졌지만 Qwen 원본 상담자의 반복은 남았다.

- 신규 생성: 10세션 / 117상담자 응답.
- 대화 방식: `adaptive_gpt_client`.
- [당시 코드 세트](../../code/gpt_client_20261006)
- [설정·출처·해시](record.json)
- [counselor.txt](prompts/counselor.txt)

상담자는 원본 Qwen으로 고정. 두 GPT는 내담자 역할이다. 상담자 192토큰 상한 종료 5회가 한 분기에 집중됐다.

실행 코드가 있어도 비공개 입력·어댑터·해당 환경 없이 완전 재실행은 불가능하다.
