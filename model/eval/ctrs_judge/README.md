# CTRS judge (평가 모델)

상담 대화를 입력받아 CTRS 항목별 점수(0~6)를 매기는 LLM-as-a-judge 파이프라인임. 작업 지침은 [CLAUDE.md](CLAUDE.md) 참고.

## 구조
- `prompts/`: 항목별 평가 프롬프트 원본(CACTUS 기준, 수정 금지). 파일 1개 = 항목 1개. 파일만 추가하면 자동으로 항목에 포함됨
- `ctrs_judge/`: 프롬프트 로더, 대화 직렬화, API 클라이언트, 파서, 실행기, 보조 지표 훅
- `models.json`: 비교할 judge 모델 설정(모델 ID, reasoning effort, temperature, 단가). 모델 추가는 항목만 넣으면 됨
- `datasets/`: 평가 대상 대화 jsonl (루트 `.gitignore`가 `data/`를 제외하므로 `datasets/`를 씀)
- `results/`: 실행 결과 jsonl

현재 항목 6개: general_1_understanding, general_2_interpersonal_effectiveness, general_3_collaboration, CBT_1_guided_discovery, CBT_2_focus, CBT_3_strategy

## 입력 형식 (jsonl, 한 줄 = 대화 1개)
```json
{"conversation_id": "cactus_0207", "turns": [{"role": "client", "text": "..."}, {"role": "therapist", "text": "..."}], "meta": {}}
```
챗봇 대화도 이 형식으로 변환만 하면 같은 파이프라인으로 채점됨.

## 데이터 (번역 정제 CACTUS 한국어 1000개)
```bash
python import_cactus_ko.py /path/to/cactus_selected_1000_ko_merged_final.json
```
- `datasets/cactus_ko_1000.jsonl`: 전체 1000개 (git 제외, 용량과 데이터 관리 정책 때문)
- `datasets/cactus_ko_sample20.jsonl`: 무작위 20개 샘플 (seed 0, 커밋됨)
- 원본의 `상담사:` / `내담자:` 줄을 turns로 변환함. conversation_id는 `cactus_ko_0000` 형식(원본 순서 기준)
- meta에는 attitude, cbt_technique, patterns, thought만 남기고 intake_form, cbt_plan은 제외함

## 실행
```bash
pip install -r requirements.txt
# .env(이 폴더 또는 레포 루트)에 OPENAI_API_KEY=... 설정. 커밋 금지
python run_eval.py --input datasets/sample.jsonl --dry-run            # 호출 수만 확인
python run_eval.py --input datasets/sample.jsonl --models gpt-6-luna gpt-6.1-sol   # 기본 5개 대화만
python run_eval.py --input datasets/cactus.jsonl --all --runs 3 --out results/run1.jsonl
python -m unittest discover -s tests -v                              # API 없이 테스트
```
- 기본은 대화 5개만 채점함(비용 보호). 전체는 `--all`
- 같은 `--out`으로 다시 실행하면 완료분은 건너뛰고 이어서 진행함. API 실패 건은 재실행 시 새 줄로 추가되므로, 분석 시 같은 키의 마지막 줄을 사용할 것

## 결과 스키마 (jsonl 1줄 = 대화 x judge x 항목 x 회차)
conversation_id, conversation(원문 전문), meta, judge, item, run_index, score, explanation, raw_response, parse_ok, parse_error, api_error, prompt_sha256, returned_model, temperature_config, temperature_applied, reasoning_effort, input_tokens, cached_input_tokens, output_tokens, seconds, cost_usd, timestamp, metric_* (보조 지표)

## 참고
- 파싱은 첫 번째 쉼표 기준 분리, 점수는 0~6 정수만 인정함. 실패 시 원문을 `raw_response`에 보존하고 재시도하지 않음
- 일부 추론 모델은 temperature를 거부함. 이 경우 temperature 없이 재시도하고 실제 적용값을 `temperature_applied`에 기록함
- `models.json`의 단가는 기존 `cbt_multiturn_experiments` 코드의 값을 옮긴 것이므로 실행 전 확인 필요
- 원본 프롬프트 중 `[Output]` 줄은 CBT_1에만 있음. 원본 보존 원칙에 따라 그대로 둠
