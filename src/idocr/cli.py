"""로컬 확인용 CLI. 결과를 터미널에만 출력하고 파일로 남기지 않는다.

    python -m idocr.cli raw path/to/image.jpg
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from idocr.config import get_settings
from idocr.ocr.engine import OcrEngine
from idocr.ocr.preprocess import ImageDecodeError, prepare
from idocr.privacy.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idocr")
    sub = parser.add_subparsers(dest="cmd", required=True)
    raw = sub.add_parser("raw", help="이미지 → 텍스트 줄")
    raw.add_argument("image", type=Path)
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_level)
    engine = OcrEngine(settings)

    data = args.image.read_bytes()
    started = time.perf_counter()
    try:
        prepared = prepare(data, max_side_len=settings.max_side_len, max_pixels=settings.max_image_pixels)
    except ImageDecodeError:
        print("IMAGE_DECODE_ERROR", file=sys.stderr)
        return 2
    lines = engine.run(prepared.bgr, scale=prepared.scale)
    elapsed = round((time.perf_counter() - started) * 1000)

    print(json.dumps({"lines": [asdict(l) for l in lines], "elapsed_ms": elapsed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
