"""OCR 과정 시각화: 이미지 한 장 → (1) 검출·인식된 모든 줄 (2) 구조화 결과. README용 그림을 만든다.

    python -m tools.visualize samples/specimen/resident_card.webp --out docs/images/specimen_resident.jpg

얼굴(증명사진·고스트 이미지)은 모자이크한다. 한글 폰트는 samples/fonts (python -m tools.synth.assets).
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from idocr.config import Settings
from idocr.core.judge import Thresholds
from idocr.core.pipeline import analyze
from idocr.ocr.engine import OcrEngine
from idocr.ocr.preprocess import prepare

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "samples" / "fonts" / "NotoSansKR.ttf"
WIDTH = 900  # 패널 하나의 이미지 폭
PANEL_W = 560  # 결과 표 폭

# 필드별 색 (구분 가능한 진한 색)
COLORS = {
    "name": (230, 57, 70), "rrn": (29, 53, 87), "address": (42, 157, 143), "issue_date": (233, 150, 0),
    "issuer": (131, 56, 236), "license_number": (0, 119, 182), "license_types": (214, 40, 140),
    "aptitude_period": (106, 153, 78), "serial_code": (188, 108, 37), "conditions": (90, 90, 90),
}
SKIP = {"address_lines", "name_hanja", "license_region", "name_en", "birth_date_en"}
LABEL = {"name": "이름", "rrn": "주민번호", "address": "주소", "issue_date": "발급일", "issuer": "발급기관",
         "license_number": "면허번호", "license_types": "면허종류", "aptitude_period": "적성검사",
         "serial_code": "보안코드", "conditions": "조건"}


def font(px: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), px)
    try:  # NotoSansKR은 가변 폰트
        f.set_variation_by_name("Bold" if bold else "Medium")
    except (OSError, ValueError):
        pass
    return f


def mosaic_faces(img: Image.Image, faces) -> Image.Image:
    arr = np.array(img)
    h, w = arr.shape[:2]
    for f in faces:
        pad_x, pad_y = 0.35 * (f.x1 - f.x0), 0.45 * f.h
        x0, y0 = max(0, int(f.x0 - pad_x)), max(0, int(f.y0 - pad_y))
        x1, y1 = min(w, int(f.x1 + pad_x)), min(h, int(f.y1 + pad_y))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        roi = arr[y0:y1, x0:x1]
        small = cv2.resize(roi, (max(1, (x1 - x0) // 14), max(1, (y1 - y0) // 14)), interpolation=cv2.INTER_AREA)
        arr[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    return Image.fromarray(arr)


def _fmt(v) -> str:
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if isinstance(v, dict):
        return f"{v.get('start')} ~ {v.get('end')}"
    return str(v)


def render(path: Path, engine: OcrEngine, settings: Settings) -> Image.Image:
    data = path.read_bytes()
    prepared = prepare(data, max_side_len=settings.max_side_len, max_pixels=settings.max_image_pixels,
                       min_side_len=settings.min_side_len)
    lines = engine.run(prepared.bgr, scale=prepared.scale)
    result = analyze(prepared, engine, Thresholds(), document_checks=True).to_dict()

    rgb = Image.fromarray(prepared.bgr[:, :, ::-1])
    rgb = rgb.resize(prepared.original_size)  # 원본 좌표계
    faces = engine.faces.detect(np.array(rgb)[:, :, ::-1]) if engine.faces else []
    base = mosaic_faces(rgb, faces)
    s = WIDTH / base.width
    base = base.resize((WIDTH, round(base.height * s)), Image.LANCZOS)

    def scaled(box):
        return [(x * s, y * s) for x, y in box]

    # (1) 모든 줄: 검출 박스 + 인식 글자
    left = base.copy().convert("RGBA")
    over = Image.new("RGBA", left.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    small = font(17)
    for line in lines:
        pts = scaled(line.box)
        d.polygon(pts, outline=(255, 140, 0, 255), width=2)
        tx, ty = pts[0][0], max(2, pts[0][1] - 23)
        label = f"{line.text}  {line.score:.2f}"
        tb = d.textbbox((tx, ty), label, font=small)
        d.rectangle((tb[0] - 3, tb[1] - 2, tb[2] + 3, tb[3] + 2), fill=(20, 20, 20, 200))
        d.text((tx, ty), label, font=small, fill=(255, 255, 255, 255))
    left = Image.alpha_composite(left, over).convert("RGB")

    # (2) 구조화 결과: 필드 박스 + 결과 표
    right = base.copy().convert("RGBA")
    over = Image.new("RGBA", right.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    fields, meta = result["fields"], result["field_meta"]
    for key, m in meta.items():
        if key in SKIP or not m["found"] or key not in COLORS:
            continue
        boxes = m["bbox"] if isinstance(m["bbox"][0][0], list) else [m["bbox"]]
        for b in boxes:
            d.polygon(scaled(b), outline=COLORS[key] + (255,), width=3, fill=COLORS[key] + (40,))
        x, y = scaled(boxes[0])[0]
        y = max(26, y)
        tb = d.textbbox((x, y - 24), LABEL[key], font=font(17, True))
        d.rectangle((tb[0] - 3, tb[1] - 2, tb[2] + 3, tb[3] + 2), fill=COLORS[key] + (240,))
        d.text((x, y - 24), LABEL[key], font=font(17, True), fill=(255, 255, 255, 255))
    right = Image.alpha_composite(right, over).convert("RGB")

    panel = _panel(result, right.height)
    # 위: 단계 1 / 아래: 단계 2 + 결과 표
    total_w = WIDTH + PANEL_W
    head = 44
    canvas = Image.new("RGB", (total_w, head * 2 + left.height + right.height + 12), (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    d.text((14, 8), "① 글자 검출 · 인식 (PP-OCRv5): 줄마다 박스와 인식 결과 · 신뢰도", font=font(20, True), fill=(30, 30, 30))
    canvas.paste(left, (0, head))
    y2 = head + left.height + 12
    d.text((14, y2 + 8), "② 구조화: 필드 위치 · 값 · 신뢰도 · 채택 여부", font=font(20, True), fill=(30, 30, 30))
    canvas.paste(right, (0, y2 + head))
    canvas.paste(panel, (WIDTH, y2 + head))
    return canvas


def _panel(result: dict, height: int) -> Image.Image:
    rows = []
    for key, value in result["fields"].items():
        if key in SKIP or key not in LABEL:
            continue
        m = result["field_meta"][key]
        rows.append((key, LABEL[key], "—" if value is None else _fmt(value), m["confidence"], m["accepted"]))
    checks = result.get("document_checks") or {}
    line_h, pad = 30, 14
    h = max(height, pad * 2 + 40 + line_h * (len(rows) + 4))
    img = Image.new("RGB", (PANEL_W, h), (248, 249, 251))
    d = ImageDraw.Draw(img)
    status = result["status"]
    color = {"OK": (42, 157, 143), "PARTIAL": (233, 150, 0), "FAIL": (230, 57, 70)}[status]
    d.rounded_rectangle((pad, pad, pad + 110, pad + 34), 8, fill=color)
    d.text((pad + 55, pad + 17), status, font=font(20, True), fill=(255, 255, 255), anchor="mm")
    d.text((pad + 124, pad + 17), result["document_type"], font=font(17), fill=(60, 60, 60), anchor="lm")
    y = pad + 50
    f = font(16)
    for key, label, value, conf, ok in rows:
        d.rectangle((pad, y + 7, pad + 10, y + 17), fill=COLORS.get(key, (90, 90, 90)))
        d.text((pad + 18, y), label, font=f, fill=(60, 60, 60))
        text = value if len(value) <= 26 else value[:25] + "…"
        d.text((pad + 104, y), text, font=f, fill=(20, 20, 20))
        if conf is not None:
            d.text((PANEL_W - pad - 64, y), f"{conf:.2f}", font=f, fill=(90, 90, 90))
            d.text((PANEL_W - pad - 14, y), "✓" if ok else "×", font=f,
                   fill=(42, 157, 143) if ok else (230, 57, 70))
        y += line_h
    y += 8
    d.line((pad, y, PANEL_W - pad, y), fill=(220, 220, 220), width=1)
    y += 10
    sus = checks.get("suspicious")
    d.text((pad, y), "위조 의심 신호: " + ("의심" if sus else "이상 없음"), font=f,
           fill=(230, 57, 70) if sus else (42, 157, 143))
    y += line_h
    parts = []
    if checks.get("face"):
        parts.append("얼굴 " + ("✓" if checks["face"]["ok"] else "×"))
    if checks.get("card_aspect"):
        ok = checks["card_aspect"]["ok"]
        parts.append("카드 비율 " + {True: "✓", False: "×", None: "보류"}[ok])
    if checks.get("background"):
        ok = checks["background"]["ok"]
        parts.append("바탕 색감 " + {True: "✓", False: "×", None: "보류"}[ok])
    d.text((pad, y), " · ".join(parts), font=font(15), fill=(90, 90, 90))
    if checks.get("reasons"):
        y += line_h - 6
        d.text((pad, y), "이유: " + ", ".join(checks["reasons"]), font=font(14), fill=(230, 57, 70))
    for i, w in enumerate(result.get("warnings") or []):
        y += 24 if i else line_h
        d.text((pad, y), ("경고: " if i == 0 else "         ") + w, font=font(14), fill=(120, 120, 120))
    return img


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="이미지 하나면 파일, 여러 개면 디렉터리")
    args = ap.parse_args(argv)
    settings = Settings()
    engine = OcrEngine(settings)
    for img in args.images:
        out = args.out if len(args.images) == 1 else args.out / f"{img.stem}.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        render(img, engine, settings).save(out, quality=88)
        print(f"{img} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
