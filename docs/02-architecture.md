# 02. 구조 및 단계별 구현 계획 (v3)

## 0. 범위

| 이 레포에서 함 | 이 레포에서 안 함 |
|---|---|
| **CPU OCR worker를 Docker로 띄우기** (1순위) | 성인 판정, 인증 정책 |
| 주민등록증/운전면허증 이미지 → OCR → **구조화 JSON** | 디스코드 봇, 유저 단위 재시도 제한 |
| 인식 모델 파인튜닝, 평가 하네스 | |
| 요청 메타데이터 MySQL 기록 (값은 저장 안 함) | |

## 1. 핵심 설계 원칙

- **코어와 전송 계층 분리.** `analyze(bytes, options) -> IdDocumentResult` 하나가 진입점이고, HTTP·CLI·평가 스크립트가 모두 이걸 호출.
- **이미지는 `bytes`로만.** 요청 본문 → 메모리 → RapidOCR. 임시 파일 없음.
- **로그·DB·예외 메시지에 필드 값을 남기지 않는다.** 응답으로만 나간다. 주민번호 뒷자리는 기본 마스킹 (05 문서 5절).
- **학습과 추론의 전처리 코드 공유** (train/serve skew 방지).
- **동기 API.** 비동기 작업 큐는 이미지를 어딘가에 저장해야 하므로 쓰지 않는다.

## 2. 디렉터리 구조

```
korean-id-ocr/
├─ pyproject.toml
├─ Dockerfile                  # 서빙 전용: python-slim + onnxruntime(CPU) + 모델 포함
├─ docker-compose.yml          # worker + (개발용) mysql
├─ .env.example
├─ models/                     # .gitignore. scripts/download_models.py가 SHA256 검증하며 채움
├─ scripts/
│  ├─ download_models.py
│  └─ make_synthetic.py        # 합성 카드 + 정답 JSON
├─ src/idocr/
│  ├─ config.py                # pydantic-settings
│  ├─ core/
│  │  ├─ result.py             # IdDocumentResult, Status, FailReason, DocumentType
│  │  ├─ classify.py           # 문서 종류/면 판별 (키워드: "주민등록증", "운전면허증" 등)
│  │  ├─ layout.py             # OCR 박스 → 줄/라벨-값 매칭 (공통)
│  │  ├─ extract/
│  │  │  ├─ resident_card.py
│  │  │  └─ driver_license.py
│  │  ├─ normalize.py          # 날짜, 주민번호, 면허번호, OCR 혼동 문자 보정
│  │  ├─ validate.py           # 필드별 형식 검증
│  │  └─ pipeline.py           # analyze() — 전처리 → OCR → 분류 → 추출 → 검증, 실패 시 재시도 패스
│  ├─ ocr/
│  │  ├─ engine.py             # RapidOCR 래퍼 (프로세스당 1회 로드)
│  │  └─ preprocess.py         # EXIF 회전·리사이즈(항상), CLAHE·90°/270°(실패 시)
│  ├─ privacy/logging.py       # 숫자열 마스킹 필터, 안전한 예외 포맷
│  ├─ storage/
│  │  ├─ models.py             # SQLAlchemy: ocr_requests 테이블
│  │  └─ repo.py               # 기록 실패해도 응답은 성공 (fire-and-forget)
│  ├─ service/
│  │  ├─ app.py                # FastAPI: /v1/ocr/raw, /v1/ocr/id, /healthz, /readyz
│  │  └─ executor.py           # 스레드풀 + 대기열 제한 + 타임아웃
│  └─ cli.py
├─ migrations/                 # alembic
├─ training/                   # 서빙 이미지에 포함 안 함 (Paddle은 여기서만)
├─ eval/
│  ├─ evaluate.py
│  └─ baselines/               # 참고 레포 Donut 등 비교용 어댑터, 별도 venv
├─ tests/
│  ├─ unit/                    # normalize, validate, layout, extract(OCR 결과 픽스처로)
│  ├─ ocr/                     # 합성 이미지 end-to-end
│  └─ fixtures/                # 합성만. 실물 절대 커밋 금지
└─ docs/
```

## 3. API

| 엔드포인트 | 용도 |
|---|---|
| `POST /v1/ocr/raw` | 이미지 → 텍스트 줄 + 박스 + 점수. Phase 1 산출물, 디버그/평가용. 운영에서는 설정으로 비활성 가능 |
| `POST /v1/ocr/id` | 이미지 → 05 문서의 구조화 JSON. `document_type` 힌트(선택) |
| `GET /healthz` / `/readyz` | 프로세스 생존 / 모델 로드 완료 |

- 입력: multipart `image` (JPEG/PNG/WebP, 크기 상한 설정), 내부망 + Bearer 토큰.
- 처리: `await run_in_executor(pool, analyze, bytes)` → 응답 후 `bytes` 참조 해제.

## 4. 운영 구성 (8코어 서버, 결정됨)

- 단일 컨테이너, uvicorn 워커 1개(모델 1벌) + 내부 스레드풀.
- 시작값: `OCR_WORKERS=2`, `ORT_INTRA_THREADS=3` → 6코어 사용, 2코어는 API·디코딩·OS. 부하 테스트 후 조정.
- **메모리 제한**: 다른 컨테이너가 메모리를 많이 쓰므로 `mem_limit`을 명시 (예: 2GB에서 시작, 측정 후 조정).
  onnxruntime `enable_cpu_mem_arena=false`(rapidocr 기본값) 유지해 메모리 증가를 억제.
- 모델은 이미지에 포함(런타임 외부 다운로드 없음). read-only rootfs, non-root, 코어 덤프 off.

## 5. MySQL 기록 (결정됨)

목적: 운영 모니터링과 **파인튜닝 대상 선정**(어떤 필드가 자주 실패하는가). 필드 **값은 저장하지 않는다.**

```sql
CREATE TABLE ocr_requests (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  request_id    CHAR(26) NOT NULL UNIQUE,     -- ULID
  created_at    DATETIME(3) NOT NULL,
  document_type VARCHAR(32) NOT NULL,         -- RESIDENT_CARD / DRIVER_LICENSE / UNKNOWN
  status        VARCHAR(16) NOT NULL,         -- OK / PARTIAL / FAIL
  fail_reason   VARCHAR(32) NULL,
  field_quality JSON NOT NULL,                -- {"name": {"found": true, "valid": true, "conf": 0.98}, ...}
  preprocess    JSON NOT NULL,                -- 회전, 패스 수
  elapsed_ms    INT NOT NULL,
  model_version VARCHAR(128) NOT NULL,
  image_bytes   INT NOT NULL,
  image_w       INT NULL,
  image_h       INT NULL
);
```

- SQLAlchemy 2.x + PyMySQL, alembic 마이그레이션. DB 장애 시에도 OCR 응답은 정상 반환(기록만 누락, 경고 로그).
- 보관 기간은 설정 (예: 90일 후 삭제 배치).

## 6. 단계별 계획

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **1. Docker OCR worker** | 모델 다운로드 스크립트(SHA256), RapidOCR 래퍼, `/v1/ocr/raw`, `/healthz`, Dockerfile, compose, 로깅 필터 | 8코어 서버에서 컨테이너 기동, 샘플 이미지 텍스트 반환, 장당 지연·메모리 측정 |
| **2. 구조화 v1 (주민등록증)** | `classify`, `layout`, `normalize`, `validate`, `resident_card`, `/v1/ocr/id` | 합성 평가셋 필드 정확도 기준선, 본인 카드(로컬) 통과 |
| **3. 구조화 v1 (운전면허증)** | `driver_license` 추출 | 동일 |
| **4. MySQL 기록** | 테이블, 마이그레이션, 비동기 기록 | 기록 실패 시 응답 영향 없음 테스트 |
| **5. 평가 하네스 + 기준선 비교** | `eval/`, 참고 레포 Donut 비교 (06 문서) | 비교 리포트 |
| **6. 파인튜닝** | 오류 분석 → rec 파인튜닝 → ONNX → 재평가 | 실촬영 평가셋에서 개선 수치 |
