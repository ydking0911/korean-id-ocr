# 05. 구조화 응답 스키마 (추천안 v1)

주민등록증·운전면허증 **앞면**의 모든 항목을 구조화한다. 뒷면과 모바일 신분증은 지원하지 않는다 (`UNSUPPORTED_DOCUMENT`).
실물 레이아웃 세부 사항 중 기억에 의존한 부분은 **(확인 필요)**로 표시했고, 본인 신분증(로컬)으로 검증한다.
공개 견본 이미지(홍길동, 2026-10-07 공유)로 확인한 항목은 **(견본 확인)**으로 표시.

## 1. 공통 응답 봉투

```jsonc
{
  "request_id": "2697051495a044929b4fb6b7b037ce96",  // UUID4 hex
  "status": "OK",                         // OK | PARTIAL | FAIL
  "document_type": "RESIDENT_CARD",       // RESIDENT_CARD | DRIVER_LICENSE | UNKNOWN
  "document_side": "FRONT",               // FRONT | BACK | UNKNOWN
  "fields": { /* 문서 종류별, 아래 2·3절 */ },
  "derived": { /* 다른 필드에서 계산한 값, 4절 */ },
  "field_meta": {
    "name": { "found": true, "confidence": 0.98, "bbox": [[x,y],[x,y],[x,y],[x,y]], "valid": true, "accepted": true }
    // 필드마다 하나 (값이 null이어도 키 유지: found=false, 나머지 null)
    // valid: 형식 검증 통과 / accepted: valid && confidence >= 필드 임계값
    // 여러 박스를 합친 필드(주소 등)는 bbox를 합집합 사각형으로, confidence는 최솟값으로
  },
  "warnings": ["MASKED:rrn"],             // 판정에 영향 없는 정보성 메모만 (이미지 품질 경고는 없음)
  "fail_reason": null,                    // FAIL일 때: 6절 표
  "preprocess": { "rotation": 90, "passes": 2, "contrast_enhanced": true },
  "model": { "det": "ppocrv5-det-server@sha256:abcd…", "rec": "ppocrv5-korean@…", "schema": "1.0" },
  "elapsed_ms": 412
}
```

- **status 규칙**: 6절.
- ✅ 값을 찾지 못한 필드는 `null`(키는 유지) → 클라이언트가 스키마를 고정해서 쓸 수 있다.
- ✅ `field_meta`(found·신뢰도·bbox·검증·채택 여부)는 **기본 응답에 포함**.
- ✅ 이미지 품질 사전 검사·경고는 하지 않고 바로 OCR. 품질 문제는 결과 신뢰도로 판정.
- 신뢰도가 낮은 값도 개발 단계에서는 **값은 그대로 반환**하고 `accepted=false`로 표시 (디버깅용).
- 원문 OCR 텍스트(`raw_lines`)는 기본 응답에 넣지 않는다. 디버그 옵션으로만 (운영에선 비활성).

## 2. 주민등록증 (`RESIDENT_CARD`)

| 키 | 실물 표기 | 타입 / 정규화 | 필수 | 검증 |
|---|---|---|---|---|
| `name` | 성명 (한글) | string, 공백 제거 | ✅ | 한글 2~5자(외자·복성 고려, 예외는 경고만) |
| `name_hanja` | 성명 옆 괄호 안 한자 | string \| null — **best-effort**, 인식 못 하면 `null` (status에 영향 없음) | | 한자 범위 |
| `rrn` | 주민등록번호 | `"YYMMDD-NNNNNNN"` | ✅ | 6+7자리, 생년월일 유효성, 뒷자리 첫 숫자 0~9 |
| `address` | 주소 (여러 줄) | string, 줄 결합 | ✅ | 시/도 명칭으로 시작하는지 (경고만) |
| `address_lines` | 주소 원 줄 구분 | string[] | | |
| `issue_date` | 발급일 `2020. 1. 1.` | `"YYYY-MM-DD"` | ✅ | 실제 날짜, 미래 아님 |
| `issuer` | 발급기관 `○○시 ○○구청장` | string | ✅ | `청장`/`시장`/`군수`/`구청장` 등으로 끝남 |

## 3. 운전면허증 (`DRIVER_LICENSE`)

| 키 | 실물 표기 | 타입 / 정규화 | 필수 | 검증 |
|---|---|---|---|---|
| `license_number` | 면허번호 `11-19-123456-61` | `"RR-YY-NNNNNN-CC"` | ✅ | 형식, 지역코드 표(아래) |
| `license_region` | 구형 표기 `서울 19-123456-61`의 지역명 | string \| null | | 구형이면 지역명→코드로 정규화해 `license_number`도 채움 (확인 필요) |
| `license_types` | 면허종류, 카드 **좌상단** `1종 보통` (공백 포함, 여러 개 가능) | string[] 공백 제거 정규화 (`1종대형`, `1종보통`, `1종소형`, `1종특수(대형견인/소형견인/구난)`, `2종보통`, `2종소형`, `2종원동기`) | ✅ | 허용 목록 |
| `name` | 성명 | string | ✅ | 주민등록증과 동일 |
| `rrn` | 주민등록번호 | `"YYMMDD-NNNNNNN"` | ✅ | 주민등록증과 동일 |
| `address` / `address_lines` | 주소 | string / string[] | ✅ | |
| `aptitude_period` | `적성검사 2024.01.01.` / `기 간: ~ 2024.12.31.` — **라벨과 날짜가 두 줄로 나뉨** (견본 확인) | `{ "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "kind": "APTITUDE" \| "RENEWAL" }` | ✅ | start ≤ end |
| `issue_date` | 발급일, 카드 **좌하단** `2014. 11. 21.` (점 뒤 공백) | `"YYYY-MM-DD"` | ✅ | |
| `conditions` | 조건 (예: 안경 착용, 자동변속기 등 코드) | string[] (없으면 `[]`) | | 견본에는 없음 → 실물로 확인 필요 |
| `serial_code` | 작은 사진 아래 암호일련번호 `NV676V` | string \| null | | 영대문자·숫자 6자리 (견본 확인, 케이뱅크 블로그도 "6자리 보안코드") — 경찰청 진위확인 조회에 쓰이는 값 |
| `issuer` | 발급기관 `서울지방경찰청장`(구) / `서울경찰청장`(현) | string | ✅ | `경찰청장`으로 끝남 (직인과 겹쳐 끝 글자 인식 저하 가능) |
| `name_en` / `birth_date_en` | 영문 면허증의 영문 표기 | string \| null | | 영문 면허증일 때만 (확인 필요) |

**지역코드 (확인 필요)**: 11 서울, 12 부산, 13 경기, 14 강원, 15 충북, 16 충남, 17 전북, 18 전남, 19 경북, 20 경남,
21 제주, 22 대구, 23 인천, 24 광주, 25 대전, 26 울산, 28 경기북부.

## 4. 파생 필드 (`derived`)

OCR로 읽은 값이 아니라 계산한 값. 클라이언트가 쓰기 편하도록 같이 내려준다.

| 키 | 계산 근거 | 예 |
|---|---|---|
| `birth_date` | `rrn` 앞 6자리 + 뒷자리 첫 숫자(세기) | `"1990-01-01"` |
| `sex` | 뒷자리 첫 숫자 홀/짝 | `"M"` / `"F"` |
| `is_foreign_resident` | 뒷자리 첫 숫자 5~8 | `false` |
| `license_region_name` | 면허번호 지역코드 | `"서울"` |
| `is_expired` | `aptitude_period.end` < 오늘 | `false` |

성인 여부 판정은 **이 레포 범위 밖** (호출 측이 `birth_date`로 판단).

> 참고: 2020년 10월 이후 부여된 주민번호는 뒷자리에 지역코드·검증숫자 체계가 적용되지 않으므로,
> 체크섬 검증은 쓰지 않고 형식·날짜 검증만 한다.

## 5. 주민번호 출력 정책 (결정됨)

현재는 **개발용이라 전체 출력** (`RRN_OUTPUT=full`이 기본). 운영 전환 시 마스킹(`"900101-1******"`) 기본값으로 바꿀 수 있게
설정 키만 미리 둔다. 어떤 설정이든 **로그·예외 메시지에는 남기지 않는다.**
이미지에서 뒷자리가 가려져 있으면 `rrn`은 `"900101-1******"`, `warnings`에 `MASKED:rrn`.

## 6. status 판정 규칙 (추천안)

OCR이 주는 점수는 "정확도"가 아니라 **인식 모델의 신뢰도(confidence)**다. 실제로 맞을 확률과 정확히 일치하지 않으므로,
임계값은 평가 하네스에서 "신뢰도 ≥ t 인 값이 실제로 맞은 비율"을 보고 정한다. 초기값은 아래처럼 두고 조정.

| 판정 | 조건 |
|---|---|
| `OK` | 문서 종류 판별 성공 + **모든 필수 필드 `accepted`** |
| `PARTIAL` | 문서 종류 판별 성공 + 핵심 필드(`name`, `rrn`, 면허증은 `license_number` 추가)는 `accepted` + 나머지 필수 필드 중 일부 미채택 |
| `FAIL` | 아래 `fail_reason` 중 하나 |

| `fail_reason` | 조건 |
|---|---|
| `IMAGE_DECODE_ERROR` | 이미지 디코딩 실패, 지원하지 않는 형식 |
| `NO_TEXT` | 재시도 패스까지 돌았는데 텍스트 박스 없음 |
| `UNSUPPORTED_DOCUMENT` | 주민등록증/운전면허증 앞면으로 판별 불가 (뒷면·모바일 포함) |
| `LOW_CONFIDENCE` | 핵심 필드 중 하나라도 `accepted=false` (못 찾았거나, 형식 오류이거나, 신뢰도 미달) |
| `INTERNAL` | 그 외 예외 (로그엔 예외 타입명만) |

- 재시도 패스(대비 보정, 90°/270° 회전)는 `OK`가 아닐 때 수행하고, 패스 중 **가장 좋은 결과**(OK > PARTIAL > FAIL, 동률이면 채택 필드 수·평균 신뢰도)를 반환.
- FAIL이어도 개발 단계에서는 찾은 `fields`·`field_meta`를 그대로 채워 반환 (원인 분석용).
- 초기 임계값(설정으로 조정): 숫자 필드(`rrn`, `license_number`, 날짜) **0.90**, 텍스트 필드(`name`, `issuer`) **0.85**, 주소 **0.80**, `name_hanja` 등 best-effort 필드는 판정에 미반영.

