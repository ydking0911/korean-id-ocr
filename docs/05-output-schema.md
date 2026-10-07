# 05. 구조화 응답 스키마 (추천안 v1)

주민등록증·운전면허증 **앞면**의 모든 항목을 구조화한다. 뒷면(주소 변경 이력, 지문 등)은 v2에서 검토.
실물 레이아웃 세부 사항 중 기억에 의존한 부분은 **(확인 필요)**로 표시했고, 본인 신분증(로컬)으로 검증한다.

## 1. 공통 응답 봉투

```jsonc
{
  "request_id": "01J...",                 // ULID
  "status": "OK",                         // OK | PARTIAL | FAIL
  "document_type": "RESIDENT_CARD",       // RESIDENT_CARD | DRIVER_LICENSE | UNKNOWN
  "document_side": "FRONT",               // FRONT | BACK | UNKNOWN
  "fields": { /* 문서 종류별, 아래 2·3절 */ },
  "derived": { /* 다른 필드에서 계산한 값, 4절 */ },
  "field_meta": {
    "name": { "confidence": 0.98, "bbox": [[x,y],[x,y],[x,y],[x,y]], "valid": true }
    // 필드마다 하나. valid=false면 형식 검증 실패(값은 그대로 반환)
  },
  "warnings": ["LOW_CONFIDENCE:address", "MASKED:rrn"],
  "fail_reason": null,                    // FAIL일 때: NO_TEXT | UNSUPPORTED_DOCUMENT | IMAGE_DECODE_ERROR | INTERNAL ...
  "preprocess": { "rotation": 90, "passes": 2, "contrast_enhanced": true },
  "model": { "det": "ppocrv5-det-server@sha256:abcd…", "rec": "ppocrv5-korean@…", "schema": "1.0" },
  "elapsed_ms": 412
}
```

- **status 규칙**: 필수 필드가 모두 추출·검증되면 `OK`, 일부 누락·검증 실패면 `PARTIAL`, 문서로 인식하지 못하면 `FAIL`.
- 값을 찾지 못한 필드는 `null`(키는 유지) → 클라이언트가 스키마를 고정해서 쓸 수 있다.
- 원문 OCR 텍스트(`raw_lines`)는 기본 응답에 넣지 않는다. 디버그 옵션으로만 (운영에선 비활성).

## 2. 주민등록증 (`RESIDENT_CARD`)

| 키 | 실물 표기 | 타입 / 정규화 | 필수 | 검증 |
|---|---|---|---|---|
| `name` | 성명 (한글) | string, 공백 제거 | ✅ | 한글 2~5자(외자·복성 고려, 예외는 경고만) |
| `name_hanja` | 성명 옆 괄호 안 한자 | string \| null | | 한자 범위 |
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
| `license_types` | 면허종류 (여러 개 가능) | string[] (`1종대형`, `1종보통`, `1종소형`, `1종특수(대형견인/소형견인/구난)`, `2종보통`, `2종소형`, `2종원동기`) | ✅ | 허용 목록 |
| `name` | 성명 | string | ✅ | 주민등록증과 동일 |
| `rrn` | 주민등록번호 | `"YYMMDD-NNNNNNN"` | ✅ | 주민등록증과 동일 |
| `address` / `address_lines` | 주소 | string / string[] | ✅ | |
| `aptitude_period` | 적성검사기간 / 갱신기간 `2029.01.01~2029.12.31` | `{ "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "kind": "APTITUDE" \| "RENEWAL" }` | ✅ | start ≤ end |
| `issue_date` | 발급일 | `"YYYY-MM-DD"` | ✅ | |
| `conditions` | 조건 (예: 안경 착용, 자동변속기 등 코드) | string[] | | (확인 필요: 코드 표기 방식) |
| `serial_code` | 사진 아래 암호일련번호 (영숫자 소문자 6자리 전후) | string \| null | | (확인 필요: 길이/문자셋) — 경찰청 진위확인 조회에 쓰이는 값 |
| `issuer` | 발급기관 `○○경찰청장` | string | ✅ | `경찰청장`으로 끝남 |
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

## 5. 주민번호 뒷자리 출력 정책 ⚠️

처음 정한 원칙은 "뒷자리 2~7번째 숫자는 출력하지 않는다"였고, "모든 내용 포함"과 충돌한다. 제안:

| 설정 `RRN_OUTPUT` | 응답 값 | 용도 |
|---|---|---|
| `masked` (**기본값**) | `"900101-1******"` | 대부분의 용도 |
| `full` | `"900101-1234567"` | 호출 측이 전체 번호가 꼭 필요할 때만 명시적으로 켬 |

어느 설정이든 **로그·DB·예외 메시지에는 전체 번호를 남기지 않는다** (DB에는 필드 값 자체를 저장하지 않음, 06·02 문서 참고).
이미지에서 뒷자리가 이미 가려져 있으면 `rrn`은 `"900101-1******"`, `warnings`에 `MASKED:rrn`.
