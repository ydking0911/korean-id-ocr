"""실제 모델로 엔진을 돌리는 스모크 테스트. 모델 파일이 없으면 skip.

    python scripts/download_models.py && pytest -m ocr
"""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from idocr.config import Settings
from idocr.ocr.engine import ModelCharsetError, OcrEngine, required_files
from idocr.ocr.preprocess import prepare

pytestmark = pytest.mark.ocr

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    pytest.skip("한글 폰트 없음")


def render(lines: list[str], size=(900, 300)) -> bytes:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    font = _font(48)
    for i, text in enumerate(lines):
        draw.text((40, 40 + i * 110), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def settings() -> Settings:
    s = Settings(ocr_workers=1, ort_intra_threads=2)
    missing = [k for k, p in required_files(s).items() if not p.exists()]
    if missing:
        pytest.skip(f"모델 파일 없음: {missing} (scripts/download_models.py 실행)")
    return s


@pytest.fixture(scope="module")
def engine(settings) -> OcrEngine:
    try:
        return OcrEngine(settings)
    except ModelCharsetError:
        pytest.skip("한국어 인식 모델이 아님 (IDOCR_REQUIRE_HANGUL=false로 배선만 시험 중이면 정상)")


def run(engine, settings, data: bytes):
    p = prepare(data, max_side_len=settings.max_side_len, max_pixels=settings.max_image_pixels)
    return engine.run(p.bgr, scale=p.scale)


def test_reads_digits(engine, settings):
    # 가짜 번호
    lines = run(engine, settings, render(["900101-1234567"]))
    digits = "".join(c for l in lines for c in l.text if c.isdigit())
    assert "9001011234567" in digits
    assert all(0.0 <= l.score <= 1.0 and len(l.box) == 4 for l in lines)


def test_reads_hangul(engine, settings):
    if not engine.has_hangul():
        pytest.skip("인식 모델에 한글 없음")
    lines = run(engine, settings, render(["주민등록증", "홍길동"]))
    text = "".join(l.text for l in lines)
    assert "주민등록증" in text
    assert "홍길동" in text


def test_boxes_are_in_original_coordinates(engine, settings):
    data = render(["900101-1234567"], size=(1800, 300))
    full = prepare(data, max_side_len=4000, max_pixels=settings.max_image_pixels)
    half = prepare(data, max_side_len=900, max_pixels=settings.max_image_pixels)
    assert half.scale == pytest.approx(0.5)

    box_full = engine.run(full.bgr, scale=full.scale)[0].box
    box_half = engine.run(half.bgr, scale=half.scale)[0].box
    # 축소 후 인식한 박스도 원본 좌표로 복원되어 거의 같은 위치여야 한다
    for (x1, y1), (x2, y2) in zip(box_full, box_half):
        assert abs(x1 - x2) < 12 and abs(y1 - y2) < 12


def test_rejects_non_korean_model_when_required(settings, tmp_path):
    engine = OcrEngine(Settings(**{**settings.model_dump(), "require_hangul": False}))
    if engine.has_hangul():
        pytest.skip("현재 모델은 한국어 모델")
    with pytest.raises(ModelCharsetError):
        OcrEngine(Settings(**{**settings.model_dump(), "require_hangul": True}))
