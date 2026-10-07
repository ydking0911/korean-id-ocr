"""항상 적용하는 전처리: 디코딩 → EXIF 회전 보정 → 긴 변 기준 축소.

대비 보정·90°/270° 회전 재시도는 실패 시에만 쓰므로 Phase 2 파이프라인에서 다룬다.
"""

import io
import warnings
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageDecodeError(Exception):
    """디코딩 실패. 메시지에 이미지 내용은 넣지 않는다."""


@dataclass(frozen=True)
class PreparedImage:
    bgr: np.ndarray
    original_size: tuple[int, int]  # (w, h), EXIF 회전 적용 후
    scale: float  # 원본 대비 축소 비율 (1.0 = 축소 없음)
    exif_rotated: bool


def prepare(data: bytes, *, max_side_len: int, max_pixels: int) -> PreparedImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in SUPPORTED_FORMATS:
                raise ImageDecodeError("unsupported format")
            w, h = img.size
            if w * h > max_pixels:
                raise ImageDecodeError("too many pixels")
            img.load()
    except ImageDecodeError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as e:
        raise ImageDecodeError(type(e).__name__) from None

    transposed = ImageOps.exif_transpose(img)
    exif_rotated = transposed.size != img.size or _orientation(img) not in (None, 1)
    img = transposed.convert("RGB")

    w, h = img.size
    scale = 1.0
    long_side = max(w, h)
    if long_side > max_side_len:
        scale = max_side_len / long_side
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)

    rgb = np.asarray(img)
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    return PreparedImage(bgr=bgr, original_size=(w, h), scale=scale, exif_rotated=exif_rotated)


def _orientation(img: Image.Image) -> int | None:
    try:
        return img.getexif().get(0x0112)
    except Exception:
        return None
