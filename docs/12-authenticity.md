# 12. 위조 의심 신호 (document_checks)

**판정이 아니라 관리자 수동 검증을 돕는 참고값이다.** status·필드 채택에는 영향을 주지 않는다.
CPU만 쓴다 (얼굴 검출 YuNet 232KB, 나머지는 OpenCV 기본 연산). 추가 지연은 측정 오차 수준.

## 1. 무엇을 잡고 무엇을 못 잡나

| 위조 유형 | 잡는가 | 근거 신호 |
|---|---|---|
| 종이에 위치만 맞춰 쓴(출력한) 글씨 | ✅ | 얼굴 없음 + 무채색 바탕 |
| A4 종이 통째로 | ✅ | + 카드 비율 |
| 흑백 복사본 | ✅ (과노출 사진 제외) | 무채색 바탕 |
| 종이 + 사진 오려 붙임 + 빨간 직인 | ✅ (과노출 사진 제외) | 무채색 바탕 (직인 같은 진한 색은 계산에서 뺀다) |
| **견본·실물을 컬러로 출력하거나 편집한 정교한 위조** | ❌ | 사진 한 장으로는 GPU가 있어도 확실히 못 가른다 → **공식 진위확인 조회** 필요 |
| 모니터 화면 재촬영 | ❌ (미구현) | 검증할 데이터가 없어 보류 |

## 2. 신호

| 신호 | 내용 | 판정 보류(`inconclusive`) |
|---|---|---|
| `face` | 사진 영역에 얼굴: 주민등록증은 주민번호 줄 **오른쪽**, 운전면허증은 **왼쪽**. 얼굴 높이가 주민번호 줄 높이의 2~12배 (좌하단 고스트 이미지 같은 작은 얼굴 제외) | 주민번호 줄을 못 찾음 → `FACE_NOT_CHECKED` |
| `card_aspect` | 카드 외곽선(4점)의 가로세로 비가 85.6×54mm(1.586) ±10% | 외곽선이 안 보임(카드를 잘라낸 사진) → `CARD_EDGES_NOT_VISIBLE`. 이미지 틀 비율은 값만 알려주고 판정 안 함 (사용자가 16:9로 자른 사진 오탐 방지) |
| `background` | 카드 바탕의 colorfulness(밝기 보정) ≥ 12. 영역 = 글자 박스 전체의 볼록 껍질(항상 카드 안), 글자·증명사진·진한 색 픽셀 제외 | 바탕의 절반 이상이 하얗게 날아감 → `BACKGROUND_OVEREXPOSED` |

응답 예:

```json
"document_checks": {
  "suspicious": true,
  "reasons": ["NO_FACE_IN_PHOTO_AREA", "PLAIN_BACKGROUND"],
  "inconclusive": ["CARD_EDGES_NOT_VISIBLE"],
  "face": {"found": false, "score": 0.0, "ok": false},
  "card_aspect": {"ratio": 1.589, "expected": 1.585, "method": "frame", "ok": null},
  "background": {"colorfulness": 0.5, "min": 12.0, "brightness": 241, "clipped": 0.0, "ok": false}
}
```

문서로 인식하지 못한 이미지(`UNKNOWN`)는 OCR 단계에서 이미 FAIL이라 `document_checks`가 `null`이다.
`IDOCR_DOCUMENT_CHECKS=false`면 계산하지 않는다 (얼굴 모델도 불필요).

## 3. 평가 (2026-10-07)

가짜는 `tools/synth/fakes.py`로 만들었다: 종이(paper), 종이+사진+직인(paper_photo), A4(sheet), 흑백 복사(grayscale) × 촬영 조건 8종.
임계값은 개발 세트(진짜 시드 1, 가짜 시드 11)로 정하고 **테스트 세트에서 한 번** 확인했다.

| 테스트 세트 | 장수 | suspicious |
|---|---|---|
| 진짜: 합성 홀드아웃 (시드 3) | 80 | **0%** (오탐 0) |
| 진짜: 실물 양식 샘플 | 4 | **0%** |
| 진짜: 견본 | 2 | **0%** |
| 가짜: paper | 48 | **100%** |
| 가짜: sheet (A4) | 48 | **100%** |
| 가짜: grayscale | 48 | 87.5% |
| 가짜: paper_photo | 48 | 87.5% |

- 놓친 12.5%는 전부 **과노출(bright) 조건** → `BACKGROUND_OVEREXPOSED`로 판정 보류를 알린다.
- 개발 과정: 처음엔 붙인 사진 주변 무늬·빨간 직인 때문에 paper_photo를 25%만 잡았다 → 측정 영역을 글자 영역으로 한정하고 진한 색 픽셀을 빼서 해결. 어두운 사진의 진짜 카드 오탐은 밝기 보정으로 해결.
- **한계**: 진짜 쪽은 합성 데이터가 견본 한 장에서 나왔고 실물은 4장뿐이다. 가짜도 직접 만든 것이다. 실제 위조 시도 사례가 생기면 다시 측정해야 한다.

재현:

```bash
python -m tools.synth.generate --fake paper --per-condition 3 --seed 12 \
  --conditions clean angle background bright dark small glare blur --out samples/fakes/s12/paper
python -m tools.synth.generate --grayscale ... --out samples/fakes/s12/grayscale
python -m tools.eval_checks --genuine samples/synthetic-holdout3 samples/real samples/specimen \
  --fake samples/fakes/s12 --per-group 4 --out samples/eval/checks-test
```

## 4. 위조 판별을 더 강하게 하려면 (이 레포 밖)

1. **공식 진위확인 조회** — 운전면허: 이름·주민번호·면허번호·**보안코드**, 주민등록증: 이름·주민번호·**발급일**.
   직접 연동은 자격 요건이 있어 보통 중계 업체(CODEF, 쿠콘 등)를 건당 비용으로 이용한다.
   이 레포가 보안코드 후보(`derived.serial_code_alternatives`)와 발급일을 내려주는 이유.
2. 홀로그램 반응 — 영상·여러 각도 촬영. CPU로 가능하지만 사용 흐름이 무거워진다.
3. 관리자 수동 검증 — `suspicious`·`inconclusive`가 있는 건을 우선 보게 한다.
