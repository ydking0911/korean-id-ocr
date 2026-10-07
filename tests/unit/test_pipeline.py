from datetime import date

import numpy as np
import pytest

from idocr.core.judge import Thresholds
from idocr.core.pipeline import analyze, rotate
from idocr.ocr.engine import OcrLine
from idocr.ocr.preprocess import PreparedImage
from tests.unit.test_resident_card import SPECIMEN, line

TODAY = date(2026, 10, 7)


class ScriptedEngine:
    """패스마다 정해 둔 줄 목록을 돌려주는 가짜 엔진."""

    def __init__(self, script, name="홍길동", name_score=0.93):
        self.script = list(script)
        self.calls = []
        self.recognized = (name, name_score)

    def run(self, img):
        self.calls.append(img.shape[:2])
        return self.script.pop(0) if self.script else []

    def recognize(self, crop):
        return self.recognized


def prepared(h=1000, w=1573, scale=1.0):
    return PreparedImage(bgr=np.full((h, w, 3), 200, np.uint8), original_size=(w, h), scale=scale, exif_rotated=False)


def test_ok_on_first_pass_stops():
    eng = ScriptedEngine([SPECIMEN])
    r = analyze(prepared(), eng, Thresholds(), today=TODAY).to_dict()
    assert r["status"] == "OK"
    assert r["preprocess"] == {"exif_rotated": False, "scale": 1.0, "rotation": 0, "contrast_enhanced": False, "passes": 1}
    assert len(eng.calls) == 1


def test_retries_with_contrast_and_keeps_best():
    low = [line("(대룡테크노타운 1B차)", 117, 571, 736, 641, 0.62) if "18차" in l.text else l for l in SPECIMEN]
    eng = ScriptedEngine([low, SPECIMEN])
    r = analyze(prepared(), eng, Thresholds(), today=TODAY).to_dict()
    assert r["status"] == "OK"
    assert r["preprocess"]["contrast_enhanced"] is True
    assert r["preprocess"]["passes"] == 2


def test_keeps_earlier_partial_when_later_passes_worse():
    low = [line("(대룡테크노타운 1B차)", 117, 571, 736, 641, 0.62) if "18차" in l.text else l for l in SPECIMEN]
    eng = ScriptedEngine([low, [], [], [], []])
    r = analyze(prepared(), eng, Thresholds(), today=TODAY).to_dict()
    assert r["status"] == "PARTIAL"
    assert r["preprocess"]["rotation"] == 0 and r["preprocess"]["passes"] == 5
    assert r["field_meta"]["address"]["accepted"] is False


def test_rotated_card_found_on_rot90_and_boxes_mapped_back():
    # 원본에서 아무것도 못 읽으면 회전을 먼저 시도 (180° → 90° → 270° → 대비 보정)
    eng = ScriptedEngine([[], [], SPECIMEN])
    r = analyze(prepared(h=1573, w=1000), eng, Thresholds(), today=TODAY).to_dict()
    assert r["status"] == "OK"
    assert (r["preprocess"]["rotation"], r["preprocess"]["passes"]) == (90, 3)
    assert eng.calls[2] == (1000, 1573)  # 회전된 이미지로 호출
    # 회전 좌표 (145,385) → 원본 좌표 (385, 1573-1-145)
    box = r["field_meta"]["rrn"]["bbox"]
    assert box[0] == [385, 1427]


def test_boxes_scaled_back_to_original_size():
    eng = ScriptedEngine([SPECIMEN])
    r = analyze(prepared(scale=0.5), eng, Thresholds(), today=TODAY).to_dict()
    assert r["field_meta"]["rrn"]["bbox"][0] == [290.0, 770.0]


def test_no_text():
    r = analyze(prepared(), ScriptedEngine([]), Thresholds(), today=TODAY).to_dict()
    assert (r["status"], r["fail_reason"], r["preprocess"]["passes"]) == ("FAIL", "NO_TEXT", 5)


def test_unknown_document():
    junk = [line("영수증 합계 12,000원", 100, 100, 600, 160)]
    r = analyze(prepared(), ScriptedEngine([junk] * 5), Thresholds(), today=TODAY).to_dict()
    assert (r["status"], r["fail_reason"], r["document_type"]) == ("FAIL", "UNSUPPORTED_DOCUMENT", "UNKNOWN")
    assert r["fields"] == {}


def test_driver_license_contrast_retry_upgrades_partial_to_ok():
    from tests.unit.test_driver_license import LICENSE_CONTRAST, LICENSE_ORIG

    eng = ScriptedEngine([LICENSE_ORIG, LICENSE_CONTRAST])
    r = analyze(prepared(h=995, w=1581), eng, Thresholds(), today=TODAY).to_dict()
    assert (r["status"], r["document_type"]) == ("OK", "DRIVER_LICENSE")
    assert (r["preprocess"]["contrast_enhanced"], r["preprocess"]["passes"]) == (True, 2)
    assert r["fields"]["license_number"] == "11-15-003456-07"
    assert set(r["fields"]) == set(r["field_meta"])


def test_mask_rrn_option():
    r = analyze(prepared(), ScriptedEngine([SPECIMEN]), Thresholds(), mask_rrn=True, today=TODAY).to_dict()
    assert r["fields"]["rrn"] == "800101-2******"
    assert r["derived"]["birth_date"] == "1980-01-01"


def test_null_fields_keep_keys_and_meta():
    r = analyze(prepared(), ScriptedEngine([SPECIMEN]), Thresholds(), today=TODAY).to_dict()
    assert r["fields"]["name_hanja"] is None
    assert r["field_meta"]["name_hanja"] == {"found": False, "confidence": None, "bbox": None, "valid": None,
                                             "accepted": False}
    assert set(r["fields"]) == set(r["field_meta"])
    assert isinstance(r["field_meta"]["address"]["bbox"], list) and len(r["field_meta"]["address"]["bbox"]) == 2


@pytest.mark.parametrize("deg", [90, 180, 270])
def test_rotate_inverse_roundtrip(deg):
    img = np.zeros((40, 100, 3), np.uint8)
    img[5, 80] = 255  # 원본 (x=80, y=5)
    rot, inverse = rotate(img, deg)
    ys, xs = np.nonzero(rot[:, :, 0])
    assert inverse([[int(xs[0]), int(ys[0])]]) == [[80, 5]]


def test_upside_down_tries_180_first():
    # 뒤집힌 사진: 줄 방향 분류로 글자는 읽히지만 제목이 맨 아래에 온다
    flipped = [line(l.text, 1573 - l.box[1][0], 1000 - l.box[2][1], 1573 - l.box[0][0], 1000 - l.box[0][1], l.score)
               for l in SPECIMEN]
    eng = ScriptedEngine([flipped, SPECIMEN])
    r = analyze(prepared(), eng, Thresholds(), today=TODAY).to_dict()
    assert r["status"] == "OK"
    assert (r["preprocess"]["rotation"], r["preprocess"]["passes"]) == (180, 2)


def test_vertical_text_tries_rotation_before_contrast():
    # 누운 사진인데 제목 일부가 읽혀 문서로는 인식된 경우에도 회전을 먼저 시도
    vertical = [line("주민등록증", 74, 217, 214, 806), line("서울특별시 가산디지털1로", 500, 114, 575, 823)]
    eng = ScriptedEngine([vertical, SPECIMEN])
    r = analyze(prepared(h=1573, w=1000), eng, Thresholds(), today=TODAY).to_dict()
    assert (r["status"], r["preprocess"]["rotation"], r["preprocess"]["passes"]) == ("OK", 90, 2)
