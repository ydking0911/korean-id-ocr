"""견본 이미지 → 빈 템플릿 + 직인 레이어.

    python -m tools.synth.template          # samples/synth/templates/ 에 저장

필드 영역을 지우고(cv2.inpaint) 직인의 붉은 픽셀은 알파 레이어로 따로 저장한다.
견본·템플릿 이미지는 저장소에 커밋하지 않는다 (samples/ gitignore).
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from tools.synth.layouts import LAYOUTS, Layout

ROOT = Path(__file__).resolve().parents[2]
SPECIMEN_DIR = ROOT / "samples" / "specimen"
TEMPLATE_DIR = ROOT / "samples" / "synth" / "templates"


def seal_layer(rgb: np.ndarray, boxes) -> np.ndarray:
    """직인 영역의 붉은 픽셀만 남긴 RGBA (나머지는 투명)."""
    h, w = rgb.shape[:2]
    out = np.zeros((h, w, 4), np.uint8)
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    redness = np.clip(np.minimum(r - g, r - b) - 25, 0, 80) / 80.0
    for x0, y0, x1, y1 in boxes:
        out[y0:y1, x0:x1, :3] = rgb[y0:y1, x0:x1]
        out[y0:y1, x0:x1, 3] = (redness[y0:y1, x0:x1] * 255).astype(np.uint8)
    return out


def build(layout: Layout, specimen_dir: Path = SPECIMEN_DIR) -> tuple[np.ndarray, np.ndarray]:
    rgb = np.array(Image.open(specimen_dir / layout.specimen).convert("RGB"))
    assert rgb.shape[1::-1] == layout.size, f"견본 크기가 다름: {rgb.shape[1::-1]} != {layout.size}"
    mask = np.zeros(rgb.shape[:2], np.uint8)
    for x0, y0, x1, y1 in layout.masks.values():
        mask[y0:y1, x0:x1] = 255
    for x0, y0, x1, y1 in layout.seals:  # 직인 아래 글자도 지운다 (직인은 나중에 다시 얹음)
        mask[y0:y1, x0:x1] = 255
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    filled = cv2.inpaint(bgr, mask, 9, cv2.INPAINT_TELEA)
    return cv2.cvtColor(filled, cv2.COLOR_BGR2RGB), seal_layer(rgb, layout.seals)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=TEMPLATE_DIR)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for layout in LAYOUTS.values():
        bg, seal = build(layout)
        Image.fromarray(bg).save(args.out / f"{layout.name}.png")
        Image.fromarray(seal, "RGBA").save(args.out / f"{layout.name}.seal.png")
        print(f"[ok] {layout.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
