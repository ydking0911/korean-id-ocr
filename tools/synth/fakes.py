"""위조 의심 신호 평가용 가짜: 종이에 신분증 위치대로 글씨를 쓴(출력한) 것.

    python -m tools.synth.generate --fake paper --per-condition 10 --seed 11 --out samples/fakes/paper

종류
- paper: 흰 종이(카드 크기)에 제목·라벨·값만. 사진·직인 없음
- paper_photo: paper + 카드의 사진 부분을 오려 붙이고 빨간 직인 (얼굴·색감 신호를 피하려는 시도)
- sheet: A4 비율 종이에 같은 글씨 (카드 비율 신호용)
흑백 복사본은 augment의 조건과 별개로 generate --grayscale 로 만든다.
"""

import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from tools.synth.layouts import Layout

FAKES = ("paper", "paper_photo", "sheet")

# 템플릿 좌표계에서 사진 영역 (얼굴 검출 결과에 여백을 둔 것)
PHOTO_BOX = {"resident_card": (0.69, 0.15, 0.93, 0.63), "driver_license": (0.08, 0.27, 0.34, 0.77)}

# 템플릿에 인쇄된 글자 (값이 아님). 위조자는 이것도 같이 쓴다
PRINTED = {
    "resident_card": [("주민등록증", 511, 144, 110)],
    "driver_license": [("자동차운전면허증(Driver's License)", 1100, 121, 58),
                       ("적성검사", 714, 641, 50), ("기  간", 662, 708, 46)],
}


def _paper(rng: random.Random, size: tuple[int, int]) -> Image.Image:
    w, h = size
    base = np.array([rng.randint(238, 252), rng.randint(236, 250), rng.randint(230, 246)], np.float32)
    noise = np.random.default_rng(rng.randrange(1 << 30)).normal(0, 2.5, (h, w, 1))
    grad = np.linspace(rng.uniform(-6, 0), rng.uniform(0, 6), w)[None, :, None]
    arr = np.clip(base + noise + grad, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


class FakeTemplates:
    """render()에 Templates 대신 넘긴다."""

    def __init__(self, kind: str, rng: random.Random, real, fonts):
        assert kind in FAKES, kind
        self.kind, self.rng, self.real, self.fonts = kind, rng, real, fonts

    def background(self, layout: Layout) -> Image.Image:
        w, h = layout.size
        size = (round(w * 1.08), round(w * 1.08 / 1.414)) if self.kind == "sheet" else (w, h)
        img = _paper(self.rng, size)
        draw = ImageDraw.Draw(img)
        font_name = self.rng.choice(["NanumGothic-Regular.ttf", "NotoSansKR.ttf", "NanumMyeongjo-Regular.ttf"])
        for text, x, y, px in PRINTED[layout.name]:
            draw.text((x, y), text, font=self.fonts.get(font_name, px), fill=(30, 30, 30), anchor="mm")
        if self.kind == "paper_photo":
            x0, y0, x1, y1 = PHOTO_BOX[layout.name]
            box = (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))
            photo = self.real.background(layout).crop(box).filter(ImageFilter.GaussianBlur(0.6))
            img.paste(photo, box[:2])
        return img

    def seal(self, layout: Layout) -> Image.Image:
        size = self.background_size(layout)
        if self.kind != "paper_photo":
            return Image.new("RGBA", size, (0, 0, 0, 0))
        seal = self.real.seal(layout)
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        out.paste(seal, (0, 0))
        return out

    def background_size(self, layout: Layout) -> tuple[int, int]:
        w, h = layout.size
        return (round(w * 1.08), round(w * 1.08 / 1.414)) if self.kind == "sheet" else (w, h)
