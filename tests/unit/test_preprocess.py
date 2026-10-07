import pytest

from idocr.ocr.preprocess import ImageDecodeError, prepare
from tests.conftest import make_image

LIMITS = dict(max_side_len=2000, max_pixels=40_000_000)


def test_decodes_to_bgr_without_resize():
    p = prepare(make_image((320, 200), color=(255, 0, 0)), **LIMITS)
    assert p.bgr.shape == (200, 320, 3)
    assert p.scale == 1.0
    assert p.original_size == (320, 200)
    # RGB 빨강 → BGR에서 마지막 채널이 큼
    b, g, r = p.bgr[100, 160]
    assert r > 200 and b < 50


def test_downscales_long_side_keeping_aspect():
    p = prepare(make_image((4000, 2000), fmt="PNG"), max_side_len=2000, max_pixels=40_000_000)
    assert p.bgr.shape[:2] == (1000, 2000)
    assert p.scale == pytest.approx(0.5)
    assert p.original_size == (4000, 2000)


def test_applies_exif_rotation():
    # orientation 6 = 90° 회전 필요 → 가로·세로가 바뀜
    p = prepare(make_image((320, 200), exif_orientation=6), **LIMITS)
    assert p.exif_rotated
    assert p.original_size == (200, 320)


@pytest.mark.parametrize("data", [b"", b"not an image", make_image(fmt="GIF")])
def test_rejects_invalid_or_unsupported(data):
    with pytest.raises(ImageDecodeError):
        prepare(data, **LIMITS)


def test_rejects_too_many_pixels():
    with pytest.raises(ImageDecodeError):
        prepare(make_image((1000, 1000), fmt="PNG"), max_side_len=2000, max_pixels=999_999)


def test_decode_error_message_has_no_content():
    with pytest.raises(ImageDecodeError) as exc:
        prepare(b"900101-1234567", **LIMITS)
    assert "1234567" not in str(exc.value)
