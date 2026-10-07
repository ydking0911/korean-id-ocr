import math

from idocr.core.layout import rows, text_angle, to_lines
from idocr.ocr.engine import OcrLine


def tilted(text, x0, y0, x1, y1, deg):
    """축 정렬 박스를 (0,0) 기준으로 deg만큼 돌린 4점 박스 (OCR이 기울어진 줄에 주는 형태)."""
    t = math.radians(deg)
    rot = lambda x, y: [round(x * math.cos(t) - y * math.sin(t), 1), round(x * math.sin(t) + y * math.cos(t), 1)]  # noqa: E731
    return OcrLine(text, 0.99, [rot(x0, y0), rot(x1, y0), rot(x1, y1), rot(x0, y1)])


def test_text_angle():
    lines = [tilted("서울특별시 가산디지털1로", 100, 500, 800, 570, 8), tilted("105동 902호", 820, 500, 1100, 570, 8)]
    assert math.degrees(text_angle(lines)) == pytest_approx(8)


def pytest_approx(v):
    import pytest
    return pytest.approx(v, abs=0.5)


def test_tilted_rows_are_not_interleaved():
    # 8° 기울어진 주소 두 줄. 각 줄은 두 박스로 쪼개짐.
    # 축 정렬 기준으로는 첫 줄 오른쪽 박스가 둘째 줄 왼쪽 박스보다 아래에 놓인다
    ocr = [
        tilted("충청남도 천안시", 100, 500, 600, 560, 8),
        tilted("봉화로 255", 650, 500, 1100, 560, 8),
        tilted("104동", 100, 570, 400, 630, 8),
        tilted("1507호", 430, 570, 700, 630, 8),
    ]
    grouped = rows(to_lines(ocr))
    assert [[l.text for l in r] for r in grouped] == [["충청남도 천안시", "봉화로 255"], ["104동", "1507호"]]


def test_small_tilt_keeps_original_geometry():
    lines = to_lines([tilted("서울특별시 가산디지털1로", 100, 500, 800, 570, 0.5)])
    assert lines[0].geo is None
