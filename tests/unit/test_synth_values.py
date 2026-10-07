"""합성 값 생성기가 만든 가짜 값은 추출기의 검증 규칙을 모두 통과해야 한다 (어긋나면 평가가 왜곡됨)."""

import random
from datetime import date

import pytest

from idocr.core import text as T
from tools.synth import values

TODAY = date(2026, 10, 7)


@pytest.mark.parametrize("seed", range(200))
def test_resident_values_are_valid(seed):
    card = values.resident_card(random.Random(seed), TODAY)
    f, p = card["fields"], card["person"]
    (rrn,) = T.find_rrns(f["rrn"])
    assert T.rrn_is_valid(rrn, TODAY)
    issue = date.fromisoformat(f["issue_date"])
    assert issue <= TODAY and issue.year >= rrn.birth_date().year + 16
    assert T.issuer_is_valid(f["issuer"])
    assert T.repair_issuer(f["issuer"]) == (f["issuer"], False)
    assert T.address_is_valid(" ".join(p.address_parts))
    assert T.name_is_valid(p.name)
    assert T.find_dates(card["render"]["issue_date"])[0].iso == f["issue_date"]


@pytest.mark.parametrize("seed", range(200))
def test_license_values_are_valid(seed):
    card = values.driver_license(random.Random(seed), TODAY)
    f, r = card["fields"], card["render"]
    (no,) = T.find_license_numbers(f["license_number"])
    assert T.license_number_is_valid(no)
    assert f["issuer"] in T.POLICE_ISSUERS
    assert T.find_license_types(r["license_types"]) == f["license_types"]
    assert T.find_serial_code(f["serial_code"]) == f["serial_code"]
    (start,) = T.find_dates(r["aptitude_start"])
    (end,) = T.find_dates(r["aptitude_end"])
    assert (start.iso, end.iso) == (f["aptitude_period"]["start"], f["aptitude_period"]["end"])
    assert T.find_dates(r["issue_date"])[0].iso == f["issue_date"]
    (rrn,) = T.find_rrns(f["rrn"])
    assert T.rrn_is_valid(rrn, TODAY)


def test_same_seed_same_card():
    a = values.driver_license(random.Random("x"), TODAY)["fields"]
    b = values.driver_license(random.Random("x"), TODAY)["fields"]
    assert a == b


def test_synthetic_rrn_has_valid_checksum():
    import random
    from datetime import date

    from tools.synth.values import person
    rng = random.Random(0)
    for _ in range(200):
        assert T.rrn_checksum_ok(T.find_rrns(person(rng, date(2026, 10, 7)).rrn)[0])
