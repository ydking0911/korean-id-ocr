"""촬영 조건 변형. 조건 분류는 docs/08 (ID-OCR-PROJECT)의 아이디어를 따른다."""

import io
import random

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

CONDITIONS = ("clean", "angle", "rotated", "bright", "dark", "blur", "jpeg", "glare", "background", "small")
# 숫자 오인식을 일부러 유도하는 스트레스 조건 (기본 세트에는 넣지 않음, --conditions로 지정)
STRESS_CONDITIONS = ("tiny", "heavyblur", "tinyjpeg")


def _background(rng: random.Random, w: int, h: int) -> Image.Image:
    """책상·천 느낌의 배경: 단색 + 저주파 얼룩 + 결 무늬."""
    base = np.array([rng.randint(60, 200), rng.randint(50, 180), rng.randint(40, 170)], np.float32)
    nr = np.random.default_rng(rng.randrange(1 << 30))
    low = cv2.resize(nr.normal(0, 1, (h // 64 + 2, w // 64 + 2)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    grain = np.sin(np.linspace(0, rng.uniform(20, 80), w))[None, :] * rng.uniform(0, 8)
    img = base[None, None, :] + (low * rng.uniform(5, 20))[..., None] + grain[..., None] + nr.normal(0, 3, (h, w, 1))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def _place(card: Image.Image, rng: random.Random, scale: float, angle: float = 0.0) -> Image.Image:
    """배경 위에 카드를 놓는다. scale = 카드가 차지하는 비율 (회전 후 크기 기준, 잘리지 않음)."""
    rotated = card.convert("RGBA").rotate(angle, expand=True, resample=Image.BICUBIC)
    w, h = int(rotated.width / scale), int(rotated.height / scale)
    bg = _background(rng, w, h)
    x = rng.randint(0, max(0, w - rotated.width))
    y = rng.randint(0, max(0, h - rotated.height))
    bg.paste(rotated, (x, y), rotated)
    return bg


def _perspective(card: Image.Image, rng: random.Random) -> Image.Image:
    img = np.array(_place(card, rng, 0.75))
    h, w = img.shape[:2]
    d = lambda: rng.uniform(0.0, 0.08)  # noqa: E731
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * d(), h * d()], [w * (1 - d()), h * d()], [w * (1 - d()), h * (1 - d())], [w * d(), h * (1 - d())]])
    m = cv2.getPerspectiveTransform(src, dst)
    return Image.fromarray(cv2.warpPerspective(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE))


def _glare(card: Image.Image, rng: random.Random) -> Image.Image:
    """비닐·조명 반사: 가우시안 형태의 흰 하이라이트."""
    img = np.array(card).astype(np.float32)
    h, w = img.shape[:2]
    cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h
    sx, sy = rng.uniform(0.08, 0.2) * w, rng.uniform(0.05, 0.15) * h
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2) / 2) * rng.uniform(0.5, 0.85)
    img = img + (255 - img) * g[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def _shadow(img: Image.Image, rng: random.Random, strength: float) -> Image.Image:
    a = np.array(img).astype(np.float32)
    h, w = a.shape[:2]
    grad = np.linspace(1.0, 1.0 - strength, w)[None, :] if rng.random() < 0.5 else np.linspace(1.0 - strength, 1.0, h)[:, None]
    return Image.fromarray(np.clip(a * grad[..., None], 0, 255).astype(np.uint8))


def apply(card: Image.Image, condition: str, rng: random.Random) -> tuple[Image.Image, int]:
    """(변형 이미지, JPEG 품질)."""
    quality = rng.randint(85, 95)
    if condition == "clean":
        out = card
    elif condition == "angle":
        out = _perspective(card, rng)
    elif condition == "rotated":
        k = rng.choice([90, 180, 270])
        out = _place(card, rng, 0.85, angle=k + rng.uniform(-3, 3))
    elif condition == "bright":
        out = ImageEnhance.Brightness(card).enhance(rng.uniform(1.25, 1.5))
    elif condition == "dark":
        out = _shadow(ImageEnhance.Brightness(card).enhance(rng.uniform(0.45, 0.7)), rng, rng.uniform(0.2, 0.5))
    elif condition == "blur":
        out = card.filter(ImageFilter.GaussianBlur(rng.uniform(1.5, 2.8)))
    elif condition == "jpeg":
        small = card.resize((card.width * 3 // 5, card.height * 3 // 5))
        out, quality = small, rng.randint(18, 35)
    elif condition == "glare":
        out = _glare(card, rng)
    elif condition == "background":
        out = _place(card, rng, rng.uniform(0.45, 0.7), angle=rng.uniform(-8, 8))
    elif condition == "small":
        w = rng.randint(480, 700)
        out = card.resize((w, round(card.height * w / card.width)), Image.LANCZOS)
    elif condition == "tiny":  # 실물 저해상도 샘플(230px)과 비슷한 크기
        w = rng.randint(260, 380)
        out = card.resize((w, round(card.height * w / card.width)), Image.LANCZOS)
    elif condition == "heavyblur":
        out = card.filter(ImageFilter.GaussianBlur(rng.uniform(3.0, 4.5)))
    elif condition == "tinyjpeg":
        w = rng.randint(320, 450)
        out, quality = card.resize((w, round(card.height * w / card.width)), Image.LANCZOS), rng.randint(15, 30)
    else:
        raise ValueError(condition)
    return out.convert("RGB"), quality


def to_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
