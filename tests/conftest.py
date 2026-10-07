import io

import pytest
from PIL import Image


def make_image(size=(320, 200), fmt="JPEG", color=(240, 240, 240), exif_orientation: int | None = None) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    kwargs = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes() -> bytes:
    return make_image()
