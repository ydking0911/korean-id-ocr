"""템플릿 위에 가짜 값을 그려 카드 이미지와 정답(gt)을 만든다."""

import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tools.synth.layouts import LAYOUTS, Layout, Slot

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = ROOT / "samples" / "fonts"
TEMPLATE_DIR = ROOT / "samples" / "synth" / "templates"

# 카드마다 하나를 고른다. 한자는 Noto 계열에만 있다
BODY_FONTS = ["NanumGothic-Regular.ttf", "GothicA1-Regular.ttf", "NotoSansKR.ttf", "NanumMyeongjo-Regular.ttf",
              "NotoSerifKR.ttf", "NanumGothicCoding-Regular.ttf"]
HANJA_FONTS = {"NanumMyeongjo-Regular.ttf": "NotoSerifKR.ttf", "NotoSerifKR.ttf": "NotoSerifKR.ttf"}


class Fonts:
    def __init__(self, font_dir: Path = FONT_DIR):
        self.dir = font_dir
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        missing = [f for f in BODY_FONTS if not (font_dir / f).exists()]
        if missing:
            raise FileNotFoundError(f"폰트 없음: {missing} (python -m tools.synth.assets)")

    def get(self, name: str, size: int) -> ImageFont.FreeTypeFont:
        key = (name, size)
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(str(self.dir / name), size)
        return self._cache[key]


class Templates:
    def __init__(self, template_dir: Path = TEMPLATE_DIR):
        self._bg: dict[str, Image.Image] = {}
        self._seal: dict[str, Image.Image] = {}
        for layout in LAYOUTS.values():
            bg, seal = template_dir / f"{layout.name}.png", template_dir / f"{layout.name}.seal.png"
            if not bg.exists():
                raise FileNotFoundError(f"템플릿 없음: {bg} (python -m tools.synth.template)")
            self._bg[layout.name] = Image.open(bg).convert("RGB")
            self._seal[layout.name] = Image.open(seal).convert("RGBA")

    def background(self, layout: Layout) -> Image.Image:
        return self._bg[layout.name].copy()

    def seal(self, layout: Layout) -> Image.Image:
        return self._seal[layout.name]


def _draw(draw: ImageDraw.ImageDraw, slot: Slot, text: str, font, color, size_scale: float = 1.0) -> tuple:
    anchor = "mm" if slot.align == "center" else "lm"
    draw.text((slot.x, slot.cy), text, font=font, fill=color, anchor=anchor)
    return draw.textbbox((slot.x, slot.cy), text, font=font, anchor=anchor)


def _wrap(words: list[str], font, x0: int, max_x: int) -> list[str]:
    lines, cur = [], ""
    for w in words:
        cand = f"{cur} {w}" if cur else w
        if cur and x0 + font.getlength(cand) > max_x:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def render(card: dict, rng: random.Random, fonts: Fonts, templates: Templates, mask_rrn: bool = False):
    """card(values.py 결과) → (RGB 이미지, gt dict). gt는 API 응답 fields와 같은 키."""
    layout = LAYOUTS[card["document_type"]]
    img = templates.background(layout)
    draw = ImageDraw.Draw(img)
    body = rng.choice(BODY_FONTS)
    gray = rng.randint(15, 60)
    color = (gray, gray, gray + rng.randint(0, 15))
    scale = rng.uniform(0.92, 1.05)
    f = card["fields"]
    r = card["render"]
    p = card["person"]
    gt = {k: v for k, v in f.items()}

    def font(slot: Slot, name: str = body):
        return fonts.get(name, max(10, round(slot.size * scale)))

    def put(key: str, text: str, name: str = body):
        slot = layout.slots[key]
        _draw(draw, slot, text, font(slot, name), color)

    rrn_text = f["rrn"][:8] + "******" if mask_rrn else f["rrn"]
    if mask_rrn:
        gt["rrn"] = rrn_text

    if layout.name == "resident_card":
        slot = layout.slots["name"]
        with_hanja = rng.random() < 0.8
        name_font = font(slot)
        draw.text((slot.x, slot.cy), p.name, font=name_font, fill=color, anchor="lm")
        if with_hanja:
            x = slot.x + name_font.getlength(p.name)
            hanja_font = font(slot, HANJA_FONTS.get(body, "NotoSansKR.ttf"))
            draw.text((x, slot.cy), f"({p.name_hanja})", font=hanja_font, fill=color, anchor="lm")
        else:
            gt["name_hanja"] = None
        put("rrn", rrn_text)
        put("issue_date", r["issue_date"])
        put("issuer", f["issuer"])
    else:
        put("license_types", r["license_types"])
        put("license_number", f["license_number"])
        put("name", p.name)
        put("rrn", rrn_text)
        put("aptitude_start", r["aptitude_start"])
        put("aptitude_end", r["aptitude_end"])
        put("serial_code", f["serial_code"], "NotoSansKR.ttf")
        put("issue_date", r["issue_date"])
        put("issuer", f["issuer"])

    # 주소: 슬롯 폭에 맞춰 줄바꿈, 줄 수가 넘치면 글자를 줄인다
    slots = layout.slots["address"]
    shrink = 1.0
    while True:
        afont = fonts.get(body, max(10, round(slots[0].size * scale * shrink)))
        lines = _wrap(p.address_parts, afont, slots[0].x, slots[0].max_x)
        if len(lines) <= len(slots) or shrink < 0.6:
            break
        shrink -= 0.08
    lines = lines[: len(slots)]
    for slot, text in zip(slots, lines):
        draw.text((slot.x, slot.cy), text, font=afont, fill=color, anchor="lm")
    gt["address_lines"] = lines
    gt["address"] = " ".join(lines)

    # 직인을 글자 위에 다시 얹는다
    img = Image.alpha_composite(img.convert("RGBA"), templates.seal(layout)).convert("RGB")
    return img, {"document_type": card["document_type"], "fields": gt, "font": body}
