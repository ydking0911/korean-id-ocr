from datetime import date

import pytest

from idocr.core import text as T

TODAY = date(2026, 10, 7)


@pytest.mark.parametrize(
    "raw,expected,masked",
    [
        ("800101-2345678", "800101-2345678", False),
        ("800101 - 2345678", "800101-2345678", False),
        ("8OO1O1-2345678", "800101-2345678", False),  # O → 0
        ("800101—2345678", "800101-2345678", False),
        ("8001012345678", "800101-2345678", False),
        ("800101-2******", "800101-2******", True),
        ("800101-2XXXXXX", "800101-2******", True),
        ("800101-2", "800101-2******", True),  # 스티커로 가린 경우
    ],
)
def test_find_rrn(raw, expected, masked):
    (rrn,) = T.find_rrns(raw)
    assert rrn.formatted() == expected
    assert rrn.masked is masked


@pytest.mark.parametrize("raw", ["11-15-003456-07", "2020.08.16.", "800101-234567", "NV676V"])
def test_not_rrn(raw):
    assert T.find_rrns(raw) == []


@pytest.mark.parametrize(
    "rrn,valid,birth",
    [
        ("800101-2345678", True, "1980-01-01"),
        ("050301-3123456", True, "2005-03-01"),
        ("800101-6123456", True, "1980-01-01"),  # 외국인
        ("801301-1234567", False, None),  # 13월
        ("800230-1234567", False, None),  # 2월 30일
        ("000229-3123456", True, "2000-02-29"),  # 윤년
        ("010229-3123456", False, None),
        ("300101-3123456", False, "2030-01-01"),  # 미래
        ("800101-9123456", False, "1880-01-01"),  # 1800년대 = OCR 오류로 간주
    ],
)
def test_rrn_validity(rrn, valid, birth):
    (r,) = T.find_rrns(rrn)
    assert T.rrn_is_valid(r, TODAY) is valid
    assert (r.birth_date().isoformat() if r.birth_date() else None) == birth


def test_rrn_derived():
    (r,) = T.find_rrns("050301-4123456")
    assert T.rrn_derived(r) == {"birth_date": "2005-03-01", "sex": "F", "is_foreign_resident": False}
    (r,) = T.find_rrns("800101-5123456")
    assert T.rrn_derived(r)["is_foreign_resident"] is True
    assert T.rrn_derived(r)["sex"] == "M"


@pytest.mark.parametrize(
    "raw,iso",
    [
        ("2020.08.16.", "2020-08-16"),
        ("2014. 11. 21.", "2014-11-21"),
        ("2014.11.21.서울지방경찰", "2014-11-21"),
        ("2O2O.O8.16", "2020-08-16"),
        ("2020-8-6", "2020-08-06"),
    ],
)
def test_find_date(raw, iso):
    (d,) = T.find_dates(raw)
    assert d.iso == iso


def test_impossible_date_keeps_raw():
    (d,) = T.find_dates("2020.02.30.")
    assert d.value is None and d.iso is None


@pytest.mark.parametrize(
    "raw,name",
    [("홍길동", "홍길동"), ("홍길동(洪吉洞)", "홍길동"), ("흥길동)", "흥길동"), ("홍 길 동", "홍길동"), ("(洪)", "")],
)
def test_leading_hangul(raw, name):
    assert T.leading_hangul(raw) == name


def test_hanja_in_parens():
    assert T.hanja_in_parens("홍길동(洪吉洞)") == "洪吉洞"
    assert T.hanja_in_parens("홍길동") is None
    assert T.hanja_in_parens("(대륭테크노타운 18차)") is None


@pytest.mark.parametrize(
    "raw,fixed,repaired",
    [
        ("서울특별시 금천구청장", "서울특별시 금천구청장", False),
        ("서울지방경찰", "서울지방경찰청장", True),
        ("서울특별시  금천구청", "서울특별시 금천구청장", True),
        ("경기도 양평군수", "경기도 양평군수", False),
    ],
)
def test_repair_issuer(raw, fixed, repaired):
    assert T.repair_issuer(raw) == (fixed, repaired)


def test_text_after_numbers():
    assert T.text_after_numbers("2014. 11. 21. 서울지방경찰") == "서울지방경찰"
    assert T.text_after_numbers("2020.08.16.") == ""
