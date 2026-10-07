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

## 테스트 데이터 계획 (4단계)

| 출처 | 용도 | 보관 |
|---|---|---|
| **공개 견본 이미지** (홍길동 주민등록증·운전면허증, 사용자 보유) | 레이아웃 규칙 개발, 스모크/회귀 테스트 기준 샘플 | `samples/specimen/` (gitignore) |
| **견본 기반 합성 데이터** (케이뱅크 블로그 방식 참고, 10 문서) | 필드 값을 가짜로 바꾼 대량 평가셋. 촬영 조건별(각도·회전·밝기·가림·배경·근접) 분할 — 08 문서 아이디어 | `samples/synthetic/` (gitignore), 생성 스크립트는 커밋 |
| 본인 신분증(가림) | 최종 실촬영 검증 | 로컬 전용, 저장소·평가 산출물에 남기지 않음 |

- 견본에 그려진 **파란 박스는 OCR 입력으로 쓰면 안 된다** (선이 글자 검출을 방해). 박스 없는 원본을 쓰고, 박스 위치는 필드 영역 정답(레이아웃 참고)으로만 활용.
- 정답 라벨은 이미지와 분리된 JSON(`*.gt.json`)으로 관리.
- 상세 파이프라인·준비물: 10 문서.

