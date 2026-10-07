"""주민등록증 추출 로직. OCR 없이 줄 목록(견본 이미지 실제 인식 결과 기반)으로 검증한다."""

from datetime import date

from idocr.core.classify import classify
from idocr.core.extract import resident_card
from idocr.core.judge import RESIDENT_SPEC, Thresholds, decide
from idocr.core.layout import to_lines
from idocr.core.result import DocumentType, FailReason, Status
from idocr.ocr.engine import OcrChar, OcrLine

TODAY = date(2026, 10, 7)


def line(text, x0, y0, x1, y1, score=0.99, chars=None):
    box = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    if chars is None:
        w = (x1 - x0) / max(1, len(text))
        chars = [(c, x0 + i * w, x0 + (i + 1) * w) for i, c in enumerate(text) if c != " "]
    return OcrLine(text, score, box, tuple(
        OcrChar(c, score, [[a, y0], [b, y0], [b, y1], [a, y1]]) for c, a, b in chars))


# 견본(1573x1000)을 한국어 모델로 인식한 결과
SPECIMEN = [
    line("주민등록증", 217, 74, 806, 214, 0.996),
    line("흥길동)", 151, 244, 776, 355, 0.849,
         chars=[("흥", 155, 238), ("길", 248, 326), ("동", 326, 405), (")", 710, 776)]),
    line("800101-2345678", 145, 385, 772, 460, 0.999),
    line("서울특별시 가산디지털1로", 114, 500, 823, 575, 0.994),
    line("(대륭테크노타운 18차)", 117, 571, 736, 641, 0.960),
    line("스셀", 1115, 717, 1309, 828, 0.998),  # 직인
    line("2020.08.16", 516, 743, 891, 807, 0.999),
    line("A", 1212, 787, 1240, 820, 0.680),  # 배경 노이즈
    line("서울특별시 금천구청장", 311, 801, 1316, 905, 0.968),
]


def run(ocr_lines, recognize=None):
    lines = to_lines(ocr_lines)
    doc_type, title = classify(lines)
    assert doc_type == DocumentType.RESIDENT_CARD
    return resident_card.extract(lines, title, recognize, TODAY)


def values(ex):
    return {k: (v.value if v else None) for k, v in ex.fields.items()}


def test_specimen_with_name_recrop():
    calls = []

    def recognize(q):
        calls.append(q)
        return "홍길동", 0.93

    ex = run(SPECIMEN, recognize)
    assert values(ex) == {
        "name": "홍길동",
        "name_hanja": None,
        "rrn": "800101-2345678",
        "address": "서울특별시 가산디지털1로 (대륭테크노타운 18차)",
        "address_lines": ["서울특별시 가산디지털1로", "(대륭테크노타운 18차)"],
        "issue_date": "2020-08-16",
        "issuer": "서울특별시 금천구청장",
    }
    assert ex.derived == {"birth_date": "1980-01-01", "sex": "F", "is_foreign_resident": False}
    assert ex.warnings == []
    # 재인식 영역은 한글 3글자(155~405) 주변만, 한자 영역(~776)은 포함하지 않음
    (crop,) = calls
    assert crop[0][0] < 155 and 405 < crop[1][0] < 500
    assert decide(ex, RESIDENT_SPEC, Thresholds()) == (Status.OK, None)


def test_without_recrop_low_confidence_name_fails_core():
    ex = run(SPECIMEN, recognize=None)
    assert ex.fields["name"].value == "흥길동"  # 한자 문맥 때문에 틀린 값
    status, reason = decide(ex, RESIDENT_SPEC, Thresholds())
    # 신뢰도 0.849 < 0.85 → 핵심 필드 미채택 → 틀린 이름을 OK로 내보내지 않음
    assert (status, reason) == (Status.FAIL, FailReason.LOW_CONFIDENCE)


def test_recrop_result_rejected_when_not_a_name():
    ex = run(SPECIMEN, lambda q: ("(洪", 0.99))
    assert ex.fields["name"].value == "흥길동"


def test_hanja_kept_when_model_reads_it():
    lines = [l for l in SPECIMEN if "길동" not in l.text] + [line("홍길동(洪吉洞)", 151, 244, 776, 355, 0.97)]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["name"].value == "홍길동"
    assert ex.fields["name_hanja"].value == "洪吉洞"


def test_masked_rrn():
    lines = [line("800101-2******", 145, 385, 772, 460) if "800101" in l.text else l for l in SPECIMEN]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["rrn"].value == "800101-2******"
    assert ex.fields["rrn"].valid
    assert "MASKED:rrn" in ex.warnings
    assert ex.derived["birth_date"] == "1980-01-01"


def test_invalid_rrn_date_is_not_valid():
    lines = [line("801301-2345678", 145, 385, 772, 460) if "800101" in l.text else l for l in SPECIMEN]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["rrn"].valid is False
    assert ex.derived == {}
    assert decide(ex, RESIDENT_SPEC, Thresholds())[0] == Status.FAIL


def test_ambiguous_rrn():
    lines = SPECIMEN + [line("800101-1111111", 120, 650, 700, 700)]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert "AMBIGUOUS:rrn" in ex.warnings
    assert ex.fields["rrn"].valid is False


def test_missing_rrn_leaves_fields_null():
    lines = [l for l in SPECIMEN if "800101" not in l.text]
    ex = run(lines)
    assert all(v is None for v in ex.fields.values())
    assert decide(ex, RESIDENT_SPEC, Thresholds()) == (Status.FAIL, FailReason.LOW_CONFIDENCE)


def test_issuer_cut_by_seal_is_repaired():
    lines = [line("서울특별시 금천구청", 311, 801, 1250, 905, 0.97) if "구청장" in l.text else l for l in SPECIMEN]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["issuer"].value == "서울특별시 금천구청장"
    assert "REPAIRED:issuer" in ex.warnings


def test_issue_date_before_age_17_is_invalid():
    lines = [line("1990.01.01", 516, 743, 891, 807) if "2020.08" in l.text else l for l in SPECIMEN]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["issue_date"].value == "1990-01-01"
    assert ex.fields["issue_date"].valid is False
    assert decide(ex, RESIDENT_SPEC, Thresholds())[0] == Status.PARTIAL


def test_low_confidence_address_gives_partial():
    lines = [line("(대룡테크노타운 1B차)", 117, 571, 736, 641, 0.62) if "18차" in l.text else l for l in SPECIMEN]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["address"].confidence == 0.62
    assert decide(ex, RESIDENT_SPEC, Thresholds()) == (Status.PARTIAL, None)


def test_title_with_ocr_error_still_classified():
    lines = [line("주민등록중", 217, 74, 806, 214) if l.text == "주민등록증" else l for l in SPECIMEN]
    assert classify(to_lines(lines))[0] == DocumentType.RESIDENT_CARD


def test_issuer_split_into_two_boxes_with_seal_noise():
    # 실제 JPEG 견본 인식 결과: 발급기관이 두 박스로 쪼개지고 오른쪽에 직인 노이즈 'F'
    lines = [l for l in SPECIMEN if "구청장" not in l.text] + [
        line("금천구청장", 714, 804, 1106, 909, 1.0),
        line("서울특별시", 314, 805, 744, 907, 0.999),
        line("F", 1114, 795, 1233, 902, 0.703),
    ]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["issuer"].value == "서울특별시 금천구청장"
    assert ex.fields["issuer"].boxes[0][1][0] == 1106  # 노이즈 박스까지 늘어나지 않음


def test_issuer_missing_space_after_sido():
    lines = [line("서울특별시금천구청장", 311, 801, 1316, 905, 0.97) if "구청장" in l.text else l for l in SPECIMEN]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["issuer"].value == "서울특별시 금천구청장"


def test_tilted_photo_overlapping_boxes():
    # 5° 기울어진 견본 실제 인식 결과: 발급일 박스와 발급기관 박스가 세로로 겹침
    lines = [
        line("주민등록증", 220, 143, 824, 330, 0.991),
        line("홍길동()", 174, 318, 805, 477, 0.783, chars=[("홍", 178, 260), ("길", 270, 350), ("동", 350, 430)]),
        line("800101-2345678", 177, 449, 814, 587, 0.999),
        line("서울특별시 가산디지털1로", 157, 558, 871, 705, 0.986),
        line("(대륭테크노타운 18차)", 164, 639, 792, 769, 0.969),
        line("배", 1263, 809, 1389, 931, 0.874),
        line("2020.08.16.", 579, 798, 960, 900, 0.992),
        line("서울특별시 금천구청장", 382, 844, 1184, 1014, 0.973),
    ]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["issuer"].value == "서울특별시 금천구청장"
    assert ex.fields["address"].value == "서울특별시 가산디지털1로 (대륭테크노타운 18차)"
    assert decide(ex, RESIDENT_SPEC, Thresholds())[0] == Status.OK


def test_address_row_split_into_boxes_is_joined():
    lines = [l for l in SPECIMEN if "가산" not in l.text] + [
        line("서울특별시", 114, 500, 400, 575, 0.99),
        line("가산디지털1로", 430, 500, 823, 575, 0.98),
    ]
    ex = run(lines, lambda q: ("홍길동", 0.95))
    assert ex.fields["address_lines"].value == ["서울특별시 가산디지털1로", "(대륭테크노타운 18차)"]


# 실물 샘플(2019년 발급, 1280x720): 주소 4줄(괄호가 줄을 넘어감), 좌하단 고스트 이미지의 생년월일 '820701'
REAL_RESIDENT = [
    line("주민등록증", 160, 40, 630, 110, 0.99),
    line("홍길동(洪吉童)", 140, 175, 600, 240, 0.95, chars=[("홍", 145, 200), ("길", 205, 262), ("동", 268, 320)]),
    line("820701-2345678", 120, 280, 620, 330, 0.99),
    line("서울특별시 종로구", 85, 385, 470, 425, 0.97),
    line("은천로 93, 1203동 1204호", 85, 430, 680, 470, 0.95),
    line("(봉천동, 진달래아파트", 85, 475, 555, 515, 0.94),
    line("101동 2301호)", 85, 520, 420, 560, 0.95),
    line("820701", 75, 595, 185, 625, 0.90),
    line("2019.11.28.", 440, 585, 720, 630, 0.99),
    line("행복특별시 행복구청장", 300, 640, 880, 695, 0.97),
]


def test_real_resident_layout():
    ex = run(REAL_RESIDENT, lambda q: ("홍길동", 0.96))
    v = values(ex)
    assert v["name"] == "홍길동"
    assert v["rrn"] == "820701-2345678"
    assert v["address_lines"] == ["서울특별시 종로구", "은천로 93, 1203동 1204호", "(봉천동, 진달래아파트", "101동 2301호)"]
    assert v["issue_date"] == "2019-11-28"
    assert v["issuer"] == "행복특별시 행복구청장"


# 같은 실물 샘플을 모델이 실제로 읽은 결과: 주민번호 박스 분리, 시·도 깨짐, 오른쪽 직인 노이즈가 발급일과 같은 줄
REAL_RESIDENT_OCR = [
    line("주민등록증", 149, 14, 630, 90, 0.989),
    line("홍길동", 130, 161, 330, 230, 0.888),
    line("820701", 119, 270, 340, 330, 0.999),
    line("2345678", 367, 274, 640, 334, 0.999),
    line("성울병신 종로구", 78, 365, 470, 410, 0.787),
    line("은전로 9371203동1204호", 85, 415, 680, 450, 0.859),
    line("(봉전동,진달래아파트", 81, 452, 555, 495, 0.923),
    line("101 23013)", 80, 500, 420, 540, 0.893),
    line("2019.1 28", 431, 573, 720, 620, 0.86),
    line("영록특별시", 907, 567, 1150, 615, 0.747),
    line("행복특별시", 293, 627, 580, 690, 0.999),
    line("행복구청장", 599, 626, 889, 703, 0.998),
    line("O보그자", 928, 653, 1100, 700, 0.587),
]


def test_real_resident_ocr_output():
    v = values(run(REAL_RESIDENT_OCR, lambda q: ("홍길동", 0.96)))
    assert v["rrn"] == "820701-2345678"
    assert v["address_lines"][0] == "서울특별시 종로구"  # 유일한 '종로구'로 시·도 역추론
    assert v["issue_date"] == "2019-01-28"
    assert v["issuer"] == "행복특별시 행복구청장"  # 같은 줄 직인 노이즈보다 접미사가 맞는 아래 줄


def test_ghost_birth_digits_not_prefixed_to_issuer():
    lines = [l for l in SPECIMEN if "구청장" not in l.text] + [
        line("800101", 120, 820, 300, 880, 0.99),
        line("서울특별시 금천구청장", 311, 801, 1316, 905, 0.968),
    ]
    assert run(lines, lambda q: ("홍길동", 0.95)).fields["issuer"].value == "서울특별시 금천구청장"
