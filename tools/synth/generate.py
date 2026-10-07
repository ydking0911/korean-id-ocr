"""합성 평가셋 생성.

    python -m tools.synth.assets      # 폰트
    python -m tools.synth.template    # 견본 → 빈 템플릿 (samples/specimen 필요)
    python -m tools.synth.generate --per-condition 20 --seed 1

출력: samples/synthetic/<condition>/<doc>_<n>.jpg + .gt.json, index.jsonl
같은 시드면 같은 데이터가 나온다. 개발 중 확인용과 최종 평가용은 시드를 나눠 쓴다.
"""

import argparse
import json
import random
from datetime import date
from pathlib import Path

from tools.synth import values
from tools.synth.augment import CONDITIONS, apply, to_jpeg
from tools.synth.render import Fonts, Templates, render

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "samples" / "synthetic"
GENERATORS = {"resident_card": values.resident_card, "driver_license": values.driver_license}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--per-condition", type=int, default=10, help="조건·문서마다 장수")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
    ap.add_argument("--docs", nargs="*", default=list(GENERATORS))
    ap.add_argument("--mask-ratio", type=float, default=0.1, help="주민번호 뒷자리를 가린 카드 비율")
    ap.add_argument("--today", type=date.fromisoformat, default=date(2026, 10, 7))
    args = ap.parse_args(argv)

    fonts, templates = Fonts(), Templates()
    args.out.mkdir(parents=True, exist_ok=True)
    index = []
    for cond in args.conditions:
        (args.out / cond).mkdir(exist_ok=True)
        for doc in args.docs:
            for n in range(args.per_condition):
                rng = random.Random(f"{args.seed}:{cond}:{doc}:{n}")
                card = GENERATORS[doc](rng, args.today)
                img, gt = render(card, rng, fonts, templates, mask_rrn=rng.random() < args.mask_ratio)
                img, quality = apply(img, cond, rng)
                stem = f"{doc}_{n:04d}"
                (args.out / cond / f"{stem}.jpg").write_bytes(to_jpeg(img, quality))
                gt.update({"condition": cond, "seed": args.seed})
                (args.out / cond / f"{stem}.gt.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1),
                                                                 encoding="utf-8")
                index.append({"image": f"{cond}/{stem}.jpg", "gt": f"{cond}/{stem}.gt.json",
                              "condition": cond, "document_type": gt["document_type"]})
        print(f"[ok] {cond}")
    with (args.out / "index.jsonl").open("w", encoding="utf-8") as f:
        for row in index:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(index)}장 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
