# Backend (FastAPI)

## 처음 세팅
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # 루트에 .env 생성 후 값 채우기
alembic upgrade head          # DB 테이블 생성 (앱은 테이블을 만들지 않는다)
```

## 실행
```bash
uvicorn app.main:app --reload
```
- http://localhost:8000/docs (Swagger)
- http://localhost:8000/api/v1/health

## 테스트 / 린트
```bash
pytest
ruff check .
```

## 구조
```
app/
├── main.py            # FastAPI 앱, CORS, 라우터 등록, 상담 알림 예약 확인 시작
├── db.py              # SQLAlchemy 엔진/세션 (SQLite ↔ Postgres는 DATABASE_URL로 전환)
├── models.py          # 테이블: users, conversations, messages, crisis_events, counseling_plans, push_subscriptions
├── core/              # config.py(.env 설정), security.py(JWT·비밀번호), errors.py(오류 형식)
├── api/v1/            # 엔드포인트 (docs/api-spec.md 기준)
│   ├── auth.py        #   비회원 토큰, 가입, 로그인, 비회원 → 회원 전환
│   ├── me.py          #   내 정보, 탈퇴
│   ├── conversations.py  # 대화, SSE 채팅
│   ├── plans.py       #   상담 계획, 상담 마치기, 회기·전체 요약
│   └── push.py        #   웹 푸시 구독, 테스트 알림
└── services/
    ├── llm.py         # 모델 호출 (mock / http / runpod), 동시 호출 제한·타임아웃
    ├── crisis.py      # 위기 감지 키워드, 비식별 기록
    ├── summary.py     # 다음 대화가 기억할 회기 요약 (사용자에게 안 보임)
    ├── plans.py       # 사용자에게 보여주는 회기·전체 요약, 알림 시각 계산
    ├── push.py        # 웹 푸시 발송, 상담 시간 알림 예약 확인
    └── retention.py   # 보관 기간 지난 데이터 정리
scripts/
├── check_model_api.py     # 모델 API 연결 점검
└── generate_vapid_keys.py # 웹 푸시 키 만들기
```

## 보관 기간 정리 (하루 1회 실행)
```bash
cd backend && python -m app.services.retention
```
비회원(마지막 활동 후 `GUEST_RETENTION_DAYS`), 회원 대화(`MEMBER_RETENTION_DAYS`), 위기 기록(`CRISIS_RETENTION_DAYS`) 중 기간이 지난 데이터를 지운다. 기준은 `docs/db-schema.md` §5.

## DB 마이그레이션 (Alembic)
모델(`app/models.py`)을 바꾸면 마이그레이션을 만들어 같이 커밋한다. 모델과 마이그레이션이 어긋나면 `tests/test_migrations.py` 가 실패한다.
```bash
alembic revision --autogenerate -m "설명"   # 변경분 생성 후 내용 확인
alembic upgrade head                        # 적용
alembic downgrade -1                        # 한 단계 되돌리기
```
- 로컬은 SQLite, 배포는 Supabase(`DATABASE_URL`)로 같은 마이그레이션을 쓴다.
- 새 컬럼이 NOT NULL 이면 기존 행을 위해 `server_default` 를 주거나 데이터 이전 단계를 넣는다.

## 모델 API 연결 점검
```bash
python -m scripts.check_model_api          # 기본 점검 (루트 .env 의 LLM_MODE=runpod, RUNPOD_* 값을 사용)
python -m scripts.check_model_api --all    # 2번째 턴, system 메시지, 작업 취소까지
```
키 값은 출력하지 않는다. 자세한 사용법은 `docs/demo-guide.md` 2번.
