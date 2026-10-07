# 09. 로드맵 및 진행 현황

범위: **CPU OCR worker(Docker) → 주민등록증/운전면허증 앞면 OCR → 구조화 JSON.**
세부 설계는 02(구조), 05(응답 스키마), 06(파인튜닝 판단) 문서.

상태: ✅ 완료 / 🔄 진행 중 / ⏳ 예정 / ❔ 조건부

| 단계 | 상태 | 내용 | 완료 기준 |
|---|---|---|---|
| 0. 설계 | ✅ | 범위·모델 조합·응답 스키마·status 규칙 결정 (docs 01~07) | 결정 로그(03) 🟡 없음 |
| **1. Docker OCR worker** | 🔄 | 아래 체크리스트 | 8코어 서버에서 한국어 모델로 기동 + 한글 인식 확인 |
| 2. 구조화 v1 — 주민등록증 앞면 | ⏳ | `classify`, `layout`, `normalize`, `validate`, `resident_card`, `/v1/ocr/id`, 재시도 패스(대비·90°/270°) | 합성 샘플·본인 카드(로컬) 통과 |
| 3. 구조화 v1 — 운전면허증 앞면 | ⏳ | `driver_license` 추출, 구형 지역명 면허번호 정규화 | 동일 |
| 4. 평가 하네스 | ⏳ | 합성 데이터 생성기, 필드별 정확도·CER, 실패 원인 분류(검출/인식/구조화), 신뢰도 임계값 보정, 모델 조합 비교(v5 mobile/server det, v6 small det) | 기준선 리포트, 임계값 확정 |
| 5. 파인튜닝 | ❔ | 4에서 "인식 모델의 일관된 오인식"이 주원인일 때만 | 기준선 대비 개선 |

## 1단계 체크리스트

| 항목 | 상태 | 비고 |
|---|---|---|
| 모델 매니페스트 + 다운로드/SHA256 검증 스크립트 | ✅ | `models/manifest.json`, `scripts/download_models.py` |
| RapidOCR 래퍼 (모델 경로 명시, 한글 charset self-test, 엔진 풀) | ✅ | `src/idocr/ocr/engine.py` |
| 전처리 (디코딩, EXIF 회전, 긴 변 축소, 픽셀 수 제한) | ✅ | `src/idocr/ocr/preprocess.py` |
| 로그 마스킹 필터 + 예외 타입명만 기록 | ✅ | uvicorn access log 포함 |
| HTTP: `/healthz`, `/readyz`, `/v1/ocr/raw` (raw body, 대기열·타임아웃) | ✅ | multipart는 디스크 스풀링 때문에 미지원 |
| Dockerfile (headless OpenCV, non-root, 모델 해시 검증) + compose (read-only, tmpfs, core dump off, 127.0.0.1 바인딩) | ✅ | |
| 단위 테스트 35개 + 실제 모델 스모크 테스트 | ✅ | 스모크는 v6 모델로 배선만 검증 (아래) |
| **한국어 모델로 실제 기동·한글 인식 확인** | ⏳ | 이 작업 환경은 ModelScope·HF가 차단되어 개발 PC에서 진행 필요 |
| 8코어 서버에서 `OCR_WORKERS` × `ORT_INTRA_THREADS` 조합 지연 측정 | ⏳ | 기본값 2 × 3 확정용 |
| `ppocrv5_korean_dict.txt` SHA256 manifest에 기록 | ⏳ | 다운로드 시 출력되는 값 |

### 1단계 검증 기록 (2026-10-07, 클라우드 작업 환경)

- rapidocr 휠 동봉 v6 모델로 `IDOCR_REQUIRE_HANGUL=false` 배선 검증: 컨테이너 healthy, `/v1/ocr/raw`가 `900101-1234567`(가짜 번호)을 score 1.0으로 인식.
- v6 rec는 한글이 없어 `require_hangul=true`일 때 기동 거부되는 것 확인 (의도한 안전장치).
- 컨테이너 메모리 약 400MB (워커 2, v6 small 모델 기준). 장당 지연 1~2초는 이 환경(4코어 공유) 기준이라 참고만.
- onnxruntime이 `/tmp/mat-debug-<pid>.log` **빈 파일(0바이트)**을 만든다. 내용 없음, tmpfs(메모리)라 디스크 기록 아님.
