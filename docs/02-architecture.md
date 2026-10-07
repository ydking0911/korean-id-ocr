# 02. 구조 및 단계별 구현 계획 (초안 v2)

## 0. 범위

| 이 레포에서 함 | 이 레포에서 안 함 |
|---|---|
| 주민등록증/운전면허증 이미지 → OCR → **구조화된 결과** | 디스코드 봇, 역할 부여, 유저 인증 기록 |
| 성인 판정 (만 19세 / 연 나이 19세, 설정) | 메시지 삭제 등 디스코드 측 개인정보 처리 |
| 인식 모델 파인튜닝 파이프라인 | |
| Docker로 띄우는 HTTP 추론 서비스 | |

디스코드 봇은 별도 레포에서 이 서비스를 HTTP로 호출하는 클라이언트가 된다.

## 1. 핵심 설계 원칙

- **판별 코어는 전송 계층과 분리한다.** `analyze(bytes, options) -> IdResult` 하나가 진입점이고,
  HTTP 서버·CLI·평가 스크립트가 모두 이 함수를 호출한다.
- **응답에 실리는 필드는 화이트리스트로 정한다.** 기본 응답은 `status`, `document_type`, `is_adult`뿐.
  주민번호 뒷자리 2~7번째는 어떤 설정으로도 반환하지 않는다 (애초에 추출하지 않는다).
- **이미지는 `bytes`로만 다룬다.** 요청 본문 → 메모리 → RapidOCR. 임시 파일 없음.
- **서비스는 무상태(stateless)를 기본으로 한다.** 재시도 제한은 단일 서버라서 메모리로 충분하다 (Q5 참고).
- **학습과 추론의 전처리 코드를 공유한다.** 학습/서빙 간 전처리 불일치(train/serve skew)를 막는다.

## 2. 디렉터리 구조

```
korean-id-ocr/
├─ pyproject.toml
├─ Dockerfile                  # 추론 서비스 전용 (onnxruntime CPU만)
├─ docker-compose.yml
├─ .env.example                # AGE_RULE, WORKERS, ORT_THREADS, API_TOKEN ...
├─ models/                     # .gitignore 대상. 다운로드 스크립트가 채움 (SHA256 검증)
├─ scripts/
│  ├─ download_models.py
│  ├─ make_synthetic.py        # 가짜 신분증 이미지 + 정답 JSON 생성
│  └─ bench.py                 # 지연시간/처리량 측정 (Phase 0)
├─ src/idocr/
│  ├─ config.py
│  ├─ core/
│  │  ├─ result.py             # IdResult, Status, FailReason, DocumentType
│  │  ├─ classify.py           # 주민등록증/운전면허증 판별 (키워드 기반)
│  │  ├─ extract/
│  │  │  ├─ rrn.py             # 주민번호 앞 7자리 추출·검증
│  │  │  └─ license.py         # 운전면허 번호 오탐 방지 등 (Phase 5)
│  │  ├─ age.py                # 만 나이 / 연 나이
│  │  └─ pipeline.py           # analyze(bytes) 진입점, 재시도 정책
│  ├─ ocr/
│  │  ├─ engine.py             # RapidOCR 래퍼 (프로세스당 1회 로드)
│  │  └─ preprocess.py         # EXIF 회전, 리사이즈, 대비, 회전 재시도 변형
│  ├─ privacy/
│  │  └─ logging.py            # 숫자열 마스킹 필터, 안전한 예외 포맷
│  ├─ service/
│  │  ├─ app.py                # FastAPI, /v1/analyze, /healthz
│  │  ├─ limiter.py            # 10분 3회 (메모리)
│  │  └─ executor.py           # 스레드풀 + 대기열 제한
│  └─ cli.py                   # 로컬 검증용. 결과 enum만 출력
├─ training/                   # 서빙 이미지에 포함하지 않음. Paddle은 여기서만 사용
│  ├─ README.md
│  ├─ configs/                 # PaddleOCR rec 파인튜닝 설정
│  ├─ data/                    # 합성 데이터 생성/라벨 변환
│  └─ export.sh                # Paddle → inference → paddle2onnx
├─ eval/
│  └─ evaluate.py              # 필드 단위 정확도, 실패 사유 분포
├─ tests/
│  ├─ unit/                    # rrn, age, classify, logging 필터
│  ├─ ocr/                     # 합성 이미지 end-to-end (느림, 마커 분리)
│  └─ fixtures/                # 합성 이미지만. 실물은 절대 커밋 금지
└─ docs/
```

## 3. 처리 흐름

```
POST /v1/analyze   (내부망 전용 + Bearer 토큰, multipart image, X-Subject-Id 헤더)
  │ 사전 검사: content-type, 크기 ≤ N MB, 재시도 제한(Subject 기준)
  │ await run_in_executor(pool, analyze, bytes)
  │     ├─ decode → EXIF 회전 → 긴 변 리사이즈          (항상)
  │     ├─ OCR → 문서 종류 판별 → 필드 추출 → 검증
  │     ├─ 실패 시: 대비 보정(CLAHE) → 90° → 270° 순 재시도 (첫 성공에서 중단)
  │     └─ IdResult(status, document_type, is_adult, fail_reason)
  │ del bytes
  └ 200 {"status": "OK", "document_type": "RRN_CARD", "is_adult": true, "age_rule": "MAN_19"}
```

실패 응답 예: `{"status": "FAIL", "fail_reason": "NUMBER_NOT_FOUND", "retry_remaining": 2}`

## 4. 추출 로직 메모 (rrn.py)

- 공백·하이픈 변형 정규화 후 `(\d{6})\s*[-–—~]?\s*([0-9])`. 박스가 쪼개질 수 있으므로 **같은 줄 박스를 이어붙인 문자열**에도 매칭.
- 흔한 OCR 혼동(`O→0`, `l/I/|→1`)은 숫자 패턴 주변에서만 치환.
- 검증: 월 01–12, 일자 범위(윤년), 미래 날짜 거부, 나이 상한(120세). 성별코드 `9`/`0`은 OCR 오류로 보고 거부.
- **후보가 둘 이상이고 서로 다르면 실패** (wonby1n/ai-ocr의 "처음 나온 것 채택" 실수 방지).
- 운전면허증은 면허번호 `11-12-345678-90`이 주민번호 패턴과 섞이지 않게 별도 규칙 (Phase 5).

## 5. 개인정보 처리 방침 (서비스 측)

| 위험 | 대응 |
|---|---|
| 로그에 숫자 유출 | 루트 로거에 6자리 이상 숫자열 마스킹 필터. rapidocr 로그 레벨 `error`. uvicorn access log에 본문 없음 확인 |
| 예외/트레이스백 | 코어 경계에서 모든 예외 → `FailReason.INTERNAL`, 로그엔 예외 **타입명만**. FastAPI 기본 500 핸들러 교체 |
| 디스크 기록 | 임시 파일 없음. 컨테이너 read-only rootfs + tmpfs, 코어 덤프 비활성화 |
| 네트워크 노출 | 내부망 전용 포트, Bearer 토큰. 외부 공개 안 함 |
| 메모리 잔류 | Python `bytes`는 덮어쓸 수 없음 → 참조를 빨리 끊는 수준이 한계 (문서화) |
| 학습 데이터 | 실물 이미지 수집 안 함. 합성 데이터 + 로컬 검증만 (Q7) |

## 6. 파인튜닝 방침

- **런타임 제약(PyTorch/Paddle 금지)은 서빙 이미지에만 적용.** 학습은 개발 PC(RTX 3070)의 별도 환경에서 PaddleOCR로 한다.
- 대상은 **인식(rec) 모델** 우선. 검출(det)은 신분증처럼 정형화된 문서에서 기본 모델로 충분한 경우가 많으므로,
  오류 분석에서 검출 누락이 주원인일 때만 손댄다.
- 순서: ① 기본 모델로 평가셋 오류 분석 → ② 오류가 숫자/하이픈 인식이면 합성 데이터로 rec 파인튜닝
  → ③ `paddle2onnx`로 변환 → ④ 같은 평가셋에서 비교 → ⑤ 개선 시 `models/`에 해시와 함께 등록.
- 평가셋: 합성 이미지 + (본인 신분증 가림 사진은 로컬 평가에만, 저장소/학습 데이터에 넣지 않음).

## 7. 단계별 계획

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **0. 스파이크** | 모델 확보·해시 기록, monkt vs 공식 모델 × det mobile/server, **CPU 스레드·워커 수별 지연/처리량 측정** (04 문서) | 모델 조합·서버 선택 결정 |
| **1. 순수 로직** | `rrn.py`, `age.py`, `classify.py`, `result.py` + 단위 테스트 (생일 당일, 윤년 2/29, 1999/2000년생, 외국인 5~8) | OCR 없이 테스트 통과 |
| **2. OCR 파이프라인** | `engine.py`, `preprocess.py`, `pipeline.py`, `cli.py`, 합성 데이터 생성기, `eval/` | 합성 평가셋 정확도 기준선 확보, 로그 무숫자 테스트 |
| **3. 서비스** | FastAPI, 실행기·대기열, 재시도 제한, Dockerfile, compose | 컨테이너로 기동, 부하 테스트 |
| **4. 파인튜닝** | `training/` 구성, rec 파인튜닝 → ONNX 변환 → 비교 | 기준선 대비 개선 수치 |
| **5. 운전면허증** | 문서 분류 + 면허증 추출 규칙, 합성 면허증 | 합성 면허증 평가 통과 |
