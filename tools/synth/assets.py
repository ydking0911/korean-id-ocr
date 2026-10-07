"""합성용 한글 폰트(OFL) 다운로드 + SHA256 검증. 폰트는 samples/fonts (gitignore)에 둔다.

    python -m tools.synth.assets
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

from tools.synth.render import FONT_DIR

BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONTS = {
    "NanumGothic-Regular.ttf": ("nanumgothic/NanumGothic-Regular.ttf",
                                "76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31"),
    "NanumMyeongjo-Regular.ttf": ("nanummyeongjo/NanumMyeongjo-Regular.ttf",
                                  "7ed9e8653a8ed04285d51dc343ffea6eb3d9c73afc27383ea8929ee4ffd03205"),
    "NanumGothicCoding-Regular.ttf": ("nanumgothiccoding/NanumGothicCoding-Regular.ttf",
                                      "787effd7efed2abca88ade231faa8191f4e9fcf85b1805a13ee1dc3724b72089"),
    "GothicA1-Regular.ttf": ("gothica1/GothicA1-Regular.ttf",
                             "211151bea98098c579610ab1114bb1bfe909057207db561f357b896d076c21ac"),
    "NotoSansKR.ttf": ("notosanskr/NotoSansKR%5Bwght%5D.ttf",
                       "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252"),
    "NotoSerifKR.ttf": ("notoserifkr/NotoSerifKR%5Bwght%5D.ttf",
                        "11f8d5de6f1b79195efba3828aaa2ec95c1178f5ae976fb23c8d53250a9938f3"),
}


def main() -> int:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    failed = False
    for name, (path, sha) in FONTS.items():
        dest = FONT_DIR / name
        if not dest.exists():
            print(f"[download] {name}")
            with urllib.request.urlopen(BASE + path, timeout=120) as r:
                dest.write_bytes(r.read())
        actual = hashlib.sha256(dest.read_bytes()).hexdigest()
        if actual != sha:
            print(f"[mismatch] {name}: {actual}", file=sys.stderr)
            failed = True
        else:
            print(f"[ok] {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
