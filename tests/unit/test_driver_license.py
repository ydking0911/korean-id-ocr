"""운전면허증 추출 로직. 견본 이미지 실제 인식 결과(원본·대비 보정 패스) 기반."""

from datetime import date

import pytest

from idocr.core import text as T
from idocr.core.classify import classify
from idocr.core.extract import driver_license
from idocr.core.judge import LICENSE_SPEC, Thresholds, decide
from idocr.core.layout import to_lines
from idocr.core.result import DocumentType, FailReason, Status
from tests.unit.test_resident_card import line

TODAY = date(2026, 10, 7)

# 원본 패스: 주소 둘째 줄이 태극 무늬 위에서 깨짐(0.660), 발급일+발급기관이 한 박스
LICENSE_ORIG = [
    line("1종 보통", 86, 39, 294, 109, 0.943),
    line("자동차운전면허증(Driver's License)", 715, 72, 1485, 170, 0.969),
    line("11-15-003456-07", 605, 154, 1333, 245, 0.979),
    line("홍길동", 605, 262, 809, 343, 1.000),
    line("800101-2345678", 607, 339, 1150, 408, 1.000),
    line("서울특별시 가산디지털1로", 608, 412, 1190, 478, 0.998),
    line("(≤8공)", 603, 472, 1115, 549, 0.660),
    line("18차20층", 606, 545, 852, 607, 1.000),
    line("적성검사 2024.01.01.", 610, 609, 1162, 672, 0.985),
    line("간:", 747, 671, 828, 738, 0.990),
    line("2024.12.31.", 930, 680, 1236, 734, 0.999),
    line("NV676V", 1316, 728, 1480, 776, 0.998),
    line("SAA", 842, 750, 874, 769, 0.546),
    line("2014.11.21.서울지방경찰", 601, 836, 1368, 921, 0.986),
]

# 대비 보정 패스: 제목·라벨·날짜가 각각 다른 박스로 쪼개짐
LICENSE_CONTRAST = [
    line("1종 보통", 86, 37, 296, 110, 0.974),
    line("자동차운전면허증", 718, 76, 1150, 159, 0.999),
    line("(Driver's License)", 1114, 96, 1475, 162, 0.970),
    line("11-15-003456-07", 603, 153, 1332, 246, 1.000),
    line("홍길동", 606, 262, 810, 343, 1.000),
    line("800101-2345678", 605, 335, 1152, 410, 1.000),
    line("서울특별시 가산디지털1로", 608, 411, 1191, 480, 0.990),
    line("(대륨테크노타운18차)", 600, 472, 1113, 550, 0.933),
    line("18차20층", 604, 543, 854, 608, 1.000),
    line("적성검사", 609, 608, 818, 673, 1.000),
    line("2024.01.01.", 799, 612, 1160, 673, 0.996),
    line("간", 750, 674, 810, 734, 0.989),
    line("기", 609, 675, 716, 731, 0.907),
    line("2024.12.31", 913, 678, 1229, 737, 0.980),
    line("NV676V", 1316, 730, 1480, 774, 0.998),
    line("2014.11.21.서울지방경찰", 601, 836, 1368, 921, 0.987),
]


def run(ocr_lines, recognize=None):
    lines = to_lines(ocr_lines)
    doc_type, title = classify(lines)
    assert doc_type == DocumentType.DRIVER_LICENSE
    return driver_license.extract(lines, title, recognize, TODAY)


def values(ex):
    return {k: (v.value if v else None) for k, v in ex.fields.items()}


def test_contrast_pass_specimen():
    ex = run(LICENSE_CONTRAST)
    assert values(ex) == {
        "license_number": "11-15-003456-07",
        "license_region": None,
        "license_types": ["1종보통"],
        "name": "홍길동",
        "rrn": "800101-2345678",
        "address": "서울특별시 가산디지털1로 (대륨테크노타운18차) 18차20층",
        "address_lines": ["서울특별시 가산디지털1로", "(대륨테크노타운18차)", "18차20층"],
        "aptitude_period": {"start": "2024-01-01", "end": "2024-12-31", "kind": "APTITUDE"},
        "issue_date": "2014-11-21",
        "conditions": None,
        "serial_code": "NV676V",
        "issuer": "서울지방경찰청장",
        "name_en": None,
        "birth_date_en": None,
    }
    assert ex.derived == {"birth_date": "1980-01-01", "sex": "F", "is_foreign_resident": False,
                          "license_region_name": "서울", "is_expired": True}
    assert ex.warnings == ["REPAIRED:issuer"]
    assert decide(ex, LICENSE_SPEC, Thresholds()) == (Status.OK, None)


def test_original_pass_low_address_gives_partial():
    ex = run(LICENSE_ORIG)
    v = values(ex)
    assert v["aptitude_period"] == {"start": "2024-01-01", "end": "2024-12-31", "kind": "APTITUDE"}
    assert v["issue_date"] == "2014-11-21" and v["issuer"] == "서울지방경찰청장"
    assert v["serial_code"] == "NV676V"  # 'SAA' 노이즈는 숫자가 없어 제외
    assert ex.fields["address"].confidence == 0.66
    assert decide(ex, LICENSE_SPEC, Thresholds()) == (Status.PARTIAL, None)


def test_old_format_license_number_with_region_name():
    lines = [line("서울 19-123456-61", 605, 154, 1333, 245, 0.97) if "003456" in l.text else l for l in LICENSE_CONTRAST]
    ex = run(lines)
    assert ex.fields["license_number"].value == "11-19-123456-61"
    assert ex.fields["license_region"].value == "서울"
    assert ex.derived["license_region_name"] == "서울"


def test_unknown_region_code_is_invalid():
    lines = [line("99-15-003456-07", 605, 154, 1333, 245, 0.99) if "003456" in l.text else l for l in LICENSE_CONTRAST]
    ex = run(lines)
    assert ex.fields["license_number"].valid is False
    assert decide(ex, LICENSE_SPEC, Thresholds()) == (Status.FAIL, FailReason.LOW_CONFIDENCE)


def test_multiple_license_types():
    lines = [line("1종 보통 2종 소형", 86, 39, 400, 109, 0.95) if "보통" in l.text else l for l in LICENSE_CONTRAST]
    assert run(lines).fields["license_types"].value == ["1종보통", "2종소형"]


def test_renewal_period_label():
    lines = [line("갱신기간", 609, 608, 818, 673, 0.99) if l.text == "적성검사" else l for l in LICENSE_CONTRAST]
    assert run(lines).fields["aptitude_period"].value["kind"] == "RENEWAL"


def test_reversed_period_is_invalid():
    lines = [line("2025.12.31", 913, 678, 1229, 737, 0.98) if l.text == "2024.12.31" else l for l in LICENSE_CONTRAST]
    lines = [line("2026.01.01.", 799, 612, 1160, 673, 0.99) if l.text == "2024.01.01." else l for l in lines]
    ex = run(lines)
    assert ex.fields["aptitude_period"].valid is False
    assert "is_expired" not in ex.derived


def test_not_expired():
    lines = [line("2030.12.31", 913, 678, 1229, 737, 0.98) if l.text == "2024.12.31" else l for l in LICENSE_CONTRAST]
    lines = [line("2030.01.01.", 799, 612, 1160, 673, 0.99) if l.text == "2024.01.01." else l for l in lines]
    assert run(lines).derived["is_expired"] is False


def test_issuer_must_be_police():
    lines = [line("2014.11.21.서울특별시 금천구청장", 601, 836, 1368, 921, 0.98) if "경찰" in l.text else l
             for l in LICENSE_CONTRAST]
    assert run(lines).fields["issuer"].valid is False


def test_license_number_not_taken_as_rrn():
    lines = [l for l in LICENSE_CONTRAST if "800101" not in l.text]
    ex = run(lines)
    assert ex.fields["rrn"] is None
    assert ex.fields["license_number"].value == "11-15-003456-07"
    assert decide(ex, LICENSE_SPEC, Thresholds())[0] == Status.FAIL


@pytest.mark.parametrize(
    "raw,expected",
    [("1종 보통", ["1종보통"]), ("1종대형", ["1종대형"]), ("2종 원동기", ["2종원동기"]),
     ("l종 보통", ["1종보통"]), ("1종 특수(구난)", ["1종특수(구난)"]), ("보통", [])],
)
def test_find_license_types(raw, expected):
    assert T.find_license_types(raw) == expected


@pytest.mark.parametrize("raw,code", [("NV676V", "NV676V"), ("nv676v", "NV676V"), ("SAA", None), ("123456", None)])
def test_find_serial_code(raw, code):
    assert T.find_serial_code(raw) == code


def test_address_line_with_only_house_number_is_kept():
    lines = [l for l in LICENSE_CONTRAST if "대륨" not in l.text and "18차20층" not in l.text]
    lines.insert(7, line("154", 600, 472, 700, 550, 0.99))
    ex = run(lines)
    assert ex.fields["address_lines"].value == ["서울특별시 가산디지털1로", "154"]


def test_police_issuer_snapped_to_closed_set():
    lines = [line("2014.11.21.경기남부지방경칠", 601, 836, 1368, 921, 0.95) if "경찰" in l.text else l
             for l in LICENSE_CONTRAST]
    ex = run(lines)
    assert ex.fields["issuer"].value == "경기남부지방경찰청장"
    assert ex.fields["issuer"].valid
    assert ex.warnings.count("REPAIRED:issuer") == 1


def test_address_stops_at_dates_when_label_unreadable():
    # 흐린 사진: '적성검사' 라벨을 못 읽어도 날짜 줄이 주소에 붙지 않아야 한다
    lines = [l for l in LICENSE_CONTRAST if l.text not in ("적성검사", "기", "간")]
    ex = run(lines)
    assert ex.fields["address_lines"].value == ["서울특별시 가산디지털1로", "(대륨테크노타운18차)", "18차20층"]
