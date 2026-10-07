"""로컬 확인용 CLI. 결과를 터미널에만 출력하고 파일로 남기지 않는다.

    python -m idocr.cli raw path/to/image.jpg   # 텍스트 줄
    python -m idocr.cli id path/to/image.jpg    # 구조화 결과
"""

import argparse
import json
import sys
import time
from pathlib import Path

from idocr.config import get_settings
from idocr.core.judge import Thresholds
from idocr.core.pipeline import analyze
from idocr.ocr.engine import OcrEngine
from idocr.ocr.preprocess import ImageDecodeError, prepare
from idocr.privacy.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idocr")
    sub = parser.add_subparsers(dest="cmd", required=True)
    raw = sub.add_parser("raw", help="이미지 → 텍스트 줄")
    raw.add_argument("image", type=Path)
    id_ = sub.add_parser("id", help="이미지 → 구조화 JSON")
    id_.add_argument("image", type=Path)
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_level)
    engine = OcrEngine(settings)

    data = args.image.read_bytes()
    started = time.perf_counter()
    try:
        prepared = prepare(data, max_side_len=settings.max_side_len, max_pixels=settings.max_image_pixels,
                           min_side_len=settings.min_side_len)
    except ImageDecodeError:
        print("IMAGE_DECODE_ERROR", file=sys.stderr)
        return 2
    if args.cmd == "raw":
        lines = engine.run(prepared.bgr, scale=prepared.scale)
        out = {"lines": [{"text": l.text, "score": l.score, "box": l.box} for l in lines]}
    else:
        th = Thresholds(settings.threshold_numeric, settings.threshold_text, settings.threshold_address, settings.threshold_verified)
        out = analyze(prepared, engine, th, mask_rrn=settings.rrn_output == "masked",
                      strict_checksum=settings.rrn_checksum == "strict",
                      document_checks=settings.document_checks).to_dict()
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000)

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
