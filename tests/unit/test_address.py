import pytest

from idocr.core.address import Lexicon, correct_address, fix_spacing, jamo_distance, load_lexicon


@pytest.mark.parametrize("a,b,d", [("대륨", "대륭", 1), ("테혜란", "테헤란", 1), ("광역세", "광역시", 1),
                                   ("송파규", "송파구", 1), ("서울", "서울", 0), ("가", "각", 1)])
def test_jamo_distance(a, b, d):
    assert jamo_distance(a, b) == d


@pytest.mark.parametrize(
    "raw,fixed",
    [
        ("충주시 세종길115 (자이)", "충주시 세종길 115 (자이)"),
        ("테헤란로34번길 74(주공아파트)", "테헤란로34번길 74 (주공아파트)"),  # 'XX로34번길'은 붙여 씀
        ("올림픽대로33번길26", "올림픽대로33번길 26"),
        ("봉화로144-3 (자이)", "봉화로 144-3 (자이)"),
        ("(센트럴파크)102동1602호", "(센트럴파크) 102동 1602호"),
        ("(대륭테크노타운18차) 18차20층", "(대륭테크노타운 18차) 18차 20층"),
        ("가산디지털1로", "가산디지털1로"),
    ],
)
def test_fix_spacing(raw, fixed):
    assert fix_spacing(raw) == fixed


@pytest.mark.parametrize(
    "raw,fixed,changed",
    [
        ("대전광역세 서구 대학로 1", "대전광역시 서구 대학로 1", [("대전광역세", "대전광역시")]),
        ("서울특별시 송파규 올림픽로 1", "서울특별시 송파구 올림픽로 1", [("송파규", "송파구")]),
        ("경기도 성남시 분당규 정자로 12", "경기도 성남시 분당구 정자로 12", [("분당규", "분당구")]),
        ("부산직할시 해운대구 중앙로 1", "부산직할시 해운대구 중앙로 1", []),  # 옛 지명도 사전에 있음
        ("서울특별시 중앙로 1", "서울특별시 중앙로 1", []),  # 도로명을 시·군·구로 바꾸지 않음
    ],
)
def test_correct_admin_names(raw, fixed, changed):
    c = correct_address(raw)
    assert (c.text, c.changed, c.valid) == (fixed, changed, True)


def test_garbage_is_invalid():
    assert correct_address("S간이매논가무면드").valid is False


def test_ambiguous_candidates_not_changed():
    lex = Lexicon(sido=frozenset({"가나도", "가다도"}), sgg={})
    c = correct_address("가라도 1", lex)
    assert c.changed == [] and c.valid is False


def test_extra_lexicon_corrects_road_and_building(tmp_path):
    words = tmp_path / "words.txt"
    words.write_text("테헤란로 대륭테크노타운\n", encoding="utf-8")
    lex = load_lexicon(str(words))
    c = correct_address("서울특별시 강남구 테혜란로 1 (대륨테크노타운)", lex)
    assert c.text == "서울특별시 강남구 테헤란로 1 (대륭테크노타운)"


def test_sido_inferred_from_unique_sgg():
    c = correct_address("성울병신 종로구 은천로 93")
    assert c.valid and c.text == "서울특별시 종로구 은천로 93"


def test_sido_not_inferred_from_shared_sgg():
    assert not correct_address("성울병신 중구 세종대로 1").valid  # 중구는 여러 시·도에 있다


def test_legal_dong_in_parentheses_not_forced_to_admin_dong():
    # 사전은 행정동뿐이라 '봉전동'(법정동 봉천동의 오인식)을 행정동 '봉선동'으로 바꾸면 안 된다
    assert "(봉전동," in correct_address("서울특별시 관악구 은천로 93 (봉전동,진달래아파트)").text
