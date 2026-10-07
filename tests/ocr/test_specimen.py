"""견본 이미지(samples/specimen, gitignore)로 실제 모델 end-to-end 확인. 견본·모델이 없으면 skip.

견본 변형(회전·축소·압축·밝기·흐림·배경)마다 핵심 필드가 정확해야 한다.
"""

import io
import json
from difflib import SequenceMatcher
from pathlib import Path

import pytest
from PIL import Image, ImageEnhance, ImageFilter

from idocr.config import Settings
from idocr.core.judge import Thresholds
from idocr.core.pipeline import analyze
from idocr.ocr.engine import OcrEngine, required_files
from idocr.ocr.preprocess import prepare

pytestmark = pytest.mark.ocr

SPECIMEN = Path(__file__).resolve().parents[2] / "samples" / "specimen"


def _jpeg(im: Image.Image, quality=90) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _on_desk(im: Image.Image) -> Image.Image:
    desk = Image.new("RGB", (2400, 1800), (120, 95, 70))
    desk.paste(im.resize((1100, 700)), (600, 500))
    return desk


VARIANTS = {
    "original": lambda im: _jpeg(im, 95),
    "rot90": lambda im: _jpeg(im.rotate(-90, expand=True)),
    "rot270": lambda im: _jpeg(im.rotate(90, expand=True)),
    "rot180": lambda im: _jpeg(im.rotate(180, expand=True)),
    "tilt5": lambda im: _jpeg(im.rotate(5, expand=True, fillcolor=(90, 90, 90))),
    "small640": lambda im: _jpeg(im.resize((640, round(640 * im.height / im.width)))),
    "jpeg_q30": lambda im: _jpeg(im, 30),
    "dark": lambda im: _jpeg(ImageEnhance.Brightness(im).enhance(0.45)),
    "blur": lambda im: _jpeg(im.filter(ImageFilter.GaussianBlur(2))),
    "on_desk": lambda im: _jpeg(_on_desk(im)),
}


@pytest.fixture(scope="module")
def engine():
    s = Settings(ocr_workers=1)
    if any(not p.exists() for p in required_files(s).values()):
        pytest.skip("모델 파일 없음")
    return OcrEngine(s)


def _load(name):
    img, gt = SPECIMEN / f"{name}.webp", SPECIMEN / f"{name}.gt.json"
    if not img.exists() or not gt.exists():
        pytest.skip(f"견본 없음: {img}")
    return Image.open(img).convert("RGB"), json.loads(gt.read_text(encoding="utf-8"))["fields"]


def _similarity(a: str | None, b: str) -> float:
    return SequenceMatcher(None, (a or "").replace(" ", ""), b.replace(" ", "")).ratio()


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_resident_card_variants(engine, variant):
    base, gt = _load("resident_card")
    prepared = prepare(VARIANTS[variant](base), max_side_len=2000, max_pixels=40_000_000)
    r = analyze(prepared, engine, Thresholds()).to_dict()

    assert r["document_type"] == "RESIDENT_CARD"
    assert r["status"] in ("OK", "PARTIAL"), r["fail_reason"]
    f = r["fields"]
    for key in ("name", "rrn", "issue_date", "issuer"):
        assert f[key] == gt[key], key
    # 주소는 드문 글자 오인식(예: 륭→륨)이 있을 수 있어 유사도로 본다
    assert _similarity(f["address"], gt["address"]) >= 0.9
