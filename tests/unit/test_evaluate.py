import pytest

from tools.evaluate import calibration, cer, norm, score


def test_norm_ignores_spaces_and_flattens():
    assert norm("서울특별시 가산디지털1로") == norm("서울특별시가산디지털1로")
    assert norm(["1종보통", "2종소형"]) == "1종보통|2종소형"
    assert norm({"start": "2024-01-01", "end": "2024-12-31", "kind": "APTITUDE"}) == "2024-01-01~2024-12-31"
    assert norm(None) == ""


@pytest.mark.parametrize(
    "pred,gt,expected",
    [("대륭", "대륭", 0.0), ("대륨", "대륭", 0.5), (None, "abcd", 1.0), ("abcdefgh", "ab", 1.0), ("a b", "ab", 0.0)],
)
def test_cer(pred, gt, expected):
    assert cer(pred, gt) == pytest.approx(expected)


def test_score_marks_correct_and_accepted():
    result = {
        "fields": {"name": "홍길동", "rrn": "800101-2345678", "address": "서울 1로", "issue_date": "2020-08-16",
                   "issuer": "서울특별시 금천구청"},
        "field_meta": {"name": {"confidence": 0.93, "accepted": True},
                       "issuer": {"confidence": 0.97, "accepted": True}},
    }
    gt = {"document_type": "RESIDENT_CARD",
          "fields": {"name": "홍길동", "rrn": "800101-2345678", "address": "서울 1 로", "issue_date": "2020-08-16",
                     "issuer": "서울특별시 금천구청장"}}
    s = score(result, gt)
    assert s["name"]["correct"] and s["name"]["exact"] and s["name"]["accepted"]
    assert s["address"]["correct"] and not s["address"]["exact"]  # 띄어쓰기만 다름
    assert s["issuer"]["accepted"] and not s["issuer"]["correct"]  # 오채택


def test_calibration_recommends_threshold():
    rows = [{"document_type": "RESIDENT_CARD",
             "fields": {"rrn": {"found": True, "confidence": c, "correct": ok}}}
            for c, ok in [(0.99, True)] * 60 + [(0.92, False)] * 2 + [(0.95, True)] * 10]
    text = "\n".join(calibration(rows))
    assert "| numeric | 72 | 0.93 | 100.0% |" in text and "← 추천" in text
