# korean-id-ocr

주민등록증/운전면허증 앞면 이미지를 CPU에서 OCR하고 구조화 JSON으로 돌려주는 worker.
RapidOCR + PaddleOCR PP-OCRv5 한국어 ONNX 모델, PyTorch/Paddle 없이 동작한다.

- 설계·결정 사항: [`docs/`](docs/README.md)
- 로드맵·진행 현황: [`docs/09-roadmap.md`](docs/09-roadmap.md)

## 빠른 시작 (Docker)

```bash
# 1. 모델 받기 (SHA256 검증). 빌드 전에 호스트에서 실행
python scripts/download_models.py

# 2. 설정 (개발용: /v1/ocr/raw 켜짐)
cp .env.example .env

# 3. 빌드·기동 (127.0.0.1:8000에만 노출)
docker compose up -d --build
curl http://127.0.0.1:8000/readyz

# 4. 이미지 → 텍스트 줄 (요청 본문으로 이미지 전송, multipart 아님)
curl --data-binary @image.jpg -H "Content-Type: image/jpeg" http://127.0.0.1:8000/v1/ocr/raw
```

## 로컬 개발

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python scripts/download_models.py

pytest                       # 단위 테스트 + (모델 있으면) 스모크 테스트
python -m idocr.cli raw image.jpg
uvicorn --factory idocr.service.app:create_app --port 8000
```

## 주요 설정 (`IDOCR_*` 환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `IDOCR_OCR_WORKERS` | 2 | 동시 OCR 수 (엔진 인스턴스 수) |
| `IDOCR_ORT_INTRA_THREADS` | 3 | 엔진당 onnxruntime 스레드. workers × threads ≤ 코어 수 권장 |
| `IDOCR_ENABLE_RAW_ENDPOINT` | false | `/v1/ocr/raw` (원문 그대로 반환). **운영에서는 끈다** |
| `IDOCR_MAX_IMAGE_BYTES` | 10485760 | 요청 본문 상한 |
| `IDOCR_MAX_SIDE_LEN` | 2000 | 긴 변이 이보다 크면 축소 |
| `IDOCR_QUEUE_LIMIT` | 16 | 동시 대기 요청 상한 (초과 시 503 BUSY) |
| `IDOCR_REQUEST_TIMEOUT_S` | 30 | 초과 시 504 TIMEOUT |
| `IDOCR_REQUIRE_HANGUL` | true | 인식 모델에 한글이 없으면 기동 거부 (잘못된 모델 로드 방지) |

## 개인정보 처리

- 이미지는 메모리에서만 처리하고 디스크에 쓰지 않는다 (multipart 미지원 이유).
- 로그에서 6자리 이상 숫자열은 마스킹, 예외는 타입명만 기록.
- 컨테이너는 read-only 루트 파일시스템, `/tmp`는 tmpfs, 코어 덤프 비활성화.
- 실물 신분증 이미지는 저장소에 커밋하지 않는다 (`samples/`는 gitignore).
