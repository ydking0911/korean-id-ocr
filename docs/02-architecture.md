# 02. 구조 및 단계별 구현 계획 (초안)

## 1. 핵심 설계 원칙

- **판별 코어는 디스코드와 분리한다.** `verify_image(bytes) -> VerificationResult` 하나만 외부에 노출하고,
  봇은 이 함수를 부르는 얇은 어댑터다. CLI·테스트에서 똑같이 재사용한다.
- **코어 밖으로 나가는 값은 결과 enum과 성인 여부(bool)뿐이다.** 추출한 생년월일·성별코드·OCR 원문은
  코어 함수의 지역 변수로만 존재하고 반환·로그·예외 메시지에 실리지 않는다.
- **이미지는 `bytes`로만 다룬다.** `attachment.read()` → `rapidocr`에 bytes 그대로 전달. 임시 파일 없음.

## 2. 디렉터리 구조

```
korean-id-ocr/
├─ pyproject.toml
├─ .env.example                # DISCORD_TOKEN, GUILD_ID, ADULT_ROLE_ID ...
├─ models/                     # .gitignore 대상, 다운로드 스크립트로 채움
├─ scripts/
│  ├─ download_models.py       # URL + SHA256 검증
│  └─ make_synthetic.py        # 가짜 신분증 이미지 생성
├─ src/idbot/
│  ├─ config.py                # 환경변수 로딩 (성인 기준, 워커 수, 크기 제한 등)
│  ├─ core/
│  │  ├─ result.py             # VerificationResult, FailReason enum
│  │  ├─ rrn.py                # OCR 텍스트 → (YYMMDD, 성별코드) 추출·검증
│  │  ├─ age.py                # 성인 판정 (만 나이 / 연 나이)
│  │  └─ pipeline.py           # verify_image(bytes) 진입점
│  ├─ ocr/
│  │  ├─ engine.py             # RapidOCR 래퍼 (프로세스당 1회 로드)
│  │  └─ preprocess.py         # EXIF 회전, 리사이즈, 대비 보정
│  ├─ privacy/
│  │  └─ logging.py            # 숫자열 마스킹 로그 필터, 안전한 예외 포맷
│  ├─ storage/
│  │  └─ db.py                 # SQLite (aiosqlite)
│  ├─ bot/
│  │  ├─ client.py             # discord.py Client/Bot, 실행 진입점
│  │  └─ verify_cog.py         # /인증 커맨드, 역할 부여, 동시성 제어
│  └─ cli.py                   # python -m idbot.cli img.jpg → 결과 enum만 출력
├─ tests/
│  ├─ unit/                    # rrn, age, logging 필터
│  ├─ ocr/                     # 합성 이미지 end-to-end (느림, 마커 분리)
│  └─ fixtures/                # 합성 이미지만. 실물 촬영본은 절대 커밋 금지
└─ docs/
```

## 3. 처리 흐름

```
/인증 image:<첨부>
  │ defer(ephemeral=True)               ← 3초 응답 제한 회피, 결과는 본인만 보임
  │ 사전 검사: content_type, size ≤ N MB, 쿨다운, 이미 인증됨?
  │ bytes = await attachment.read()
  │ await loop.run_in_executor(ocr_pool, verify_image, bytes)
  │     ├─ decode + EXIF 회전 + 리사이즈
  │     ├─ OCR (1차) → 후보 추출
  │     ├─ 실패 시 전처리 변형(대비/회전)으로 최대 K회 재시도
  │     └─ VerificationResult(status, is_adult)   # 숫자는 여기서 소멸
  │ del bytes
  │ 성인 → member.add_roles(role) ; DB 기록
  └ followup.send(ephemeral) : "인증 완료" / "인식 실패: 재촬영 안내" / "기준 미달"
```

## 4. 주민번호 추출 로직 (rrn.py) 메모

- 공백·하이픈 변형 정규화 후 `(\d{6})\s*[-–—~]?\s*([0-9])` 패턴. OCR 텍스트 박스가 앞/뒤로 쪼개질 수 있으므로
  **같은 줄(박스 y좌표 근접) 텍스트를 이어붙인 문자열**에도 매칭한다.
- 흔한 OCR 혼동(`O→0`, `l/I/|→1`)은 **숫자 패턴 주변에서만** 치환.
- 검증: 월 01–12, 일자는 해당 연·월 범위(윤년 포함), 미래 날짜 거부, 나이 상한(예: 120세).
- 성별코드 `9`/`0`(1800년대)은 사실상 OCR 오류이므로 **거부**하고 재촬영 안내를 제안.
- **후보가 둘 이상이고 서로 다르면 실패 처리** (wonby1n/ai-ocr의 "처음 나온 것 채택" 실수 방지).
  발급일(`2020.01.01`) 같은 날짜는 하이픈+1자리 패턴이 없어 걸러진다.
- 함수는 `bool`/enum만 반환하고 내부 값은 반환하지 않는 형태로 테스트한다.

## 5. 개인정보 처리 구현 방침

| 위험 | 대응 |
|---|---|
| 로그에 숫자 유출 | 루트 로거에 `\d{6}` 이상 연속 숫자 마스킹 필터. rapidocr 로그 레벨 `error` |
| 예외/트레이스백에 OCR 텍스트 | 코어 경계에서 모든 예외를 잡아 `FailReason.INTERNAL`로 변환, 로그엔 예외 **타입명만** |
| discord.py 기본 `on_error` | 오버라이드해서 동일하게 타입명만 기록 |
| 디스크 기록 | 임시 파일 미사용. 코어 덤프 비활성화(운영 시 `ulimit -c 0`) |
| 메모리 잔류 | Python `bytes`는 즉시 0으로 덮을 수 없음 → 참조를 빨리 끊는 수준으로 한정 (한계로 문서화) |
| 디버그 저장 기능 | 만들지 않는다. 디버깅은 합성 이미지로만 |

## 6. 단계별 계획

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **0. 스파이크** | 모델 확보·해시 기록, monkt vs 공식 모델 × det mobile/server 비교, CPU 지연·RAM 측정 | 모델 조합 결정, 1장당 처리 시간 수치 |
| **1. 순수 로직** | `rrn.py`, `age.py`, `result.py` + 단위 테스트 (경계값: 생일 당일, 윤년 2/29, 연말/연초) | OCR 없이 테스트 통과 |
| **2. OCR 파이프라인** | `engine.py`, `preprocess.py`, `pipeline.py`, `cli.py`, 합성 이미지 생성기 | 합성 샘플 인식률 측정, 로그에 숫자 없음 검증 테스트 |
| **3. 디스코드 봇** | `/인증` 커맨드, ephemeral 응답, 역할 부여, 실행기·대기열·쿨다운 | 테스트 서버에서 동작 |
| **4. 저장소·관리** | SQLite 기록, 관리자용 `/인증상태`, `/인증취소` | 재인증 방지·취소 동작 |
| **5. 하드닝·배포** | 로깅 필터 점검, 크기/형식 제한, systemd 또는 Docker, 모델 사전 탑재 | 운영 체크리스트 통과 |
| **6. 운전면허증** | 면허번호(`11-12-345678-90`) 오탐 방지 포함 추출 규칙 추가 | 합성 면허증 샘플 통과 |
