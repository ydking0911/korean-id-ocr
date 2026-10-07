"""위조 의심 신호(document_checks) 평가: 진짜(합성·실물)와 가짜(tools/synth/fakes.py)를 얼마나 가르는가.

    python -m tools.eval_checks --genuine samples/synthetic-holdout3 samples/real \\
        --fake samples/fakes/s12 --out samples/eval/checks-test

각 이미지의 신호 값과 suspicious 여부를 results.jsonl에, 신호별 오탐(진짜를 의심)·검출(가짜를 의심)을 report.md에 쓴다.
"""

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from idocr.config import Settings
from idocr.core.judge import Thresholds
from idocr.core.pipeline import analyze
from idocr.ocr.engine import EnginePool
from idocr.ocr.preprocess import ImageDecodeError, prepare

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SIGNALS = ("face", "card_aspect", "background")


def collect(dirs: list[Path], label: str, per_group: int | None) -> list[dict]:
    items = []
    for d in dirs:
        groups = defaultdict(list)
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in IMAGE_EXT and ".seal" not in p.name:
                groups[(p.parent, p.name.split("_0")[0])].append(p)  # 폴더·문서 종류별
        for (parent, _), paths in groups.items():
            kind = parent.parent.name if label == "fake" else d.name
            for p in paths[:per_group] if per_group else paths:
                items.append({"image": p, "label": label, "kind": kind, "condition": parent.name})
    return items


def run(items: list[dict], settings: Settings) -> list[dict]:
    pool = EnginePool.create(settings)
    th = Thresholds()

    def one(item):
        try:
            prepared = prepare(item["image"].read_bytes(), max_side_len=settings.max_side_len,
                               max_pixels=settings.max_image_pixels, min_side_len=settings.min_side_len)
            with pool.acquire() as engine:
                r = analyze(prepared, engine, th, document_checks=True).to_dict()
        except ImageDecodeError:
            r = {"status": "FAIL", "document_type": "UNKNOWN", "document_checks": None}
        path = item["image"]
        return {"image": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "label": item["label"], "kind": item["kind"], "condition": item["condition"],
                "status": r["status"], "document_type": r["document_type"], "checks": r.get("document_checks")}

    with ThreadPoolExecutor(max_workers=pool.size) as ex:
        return list(ex.map(one, items))


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def summarize(rows: list[dict]) -> str:
    out = ["# 위조 의심 신호 평가", "",
           "- 진짜: 오탐 = suspicious 비율 (낮을수록 좋음). 가짜: 검출 = suspicious 비율 (높을수록 좋음)",
           "- 문서로 인식되지 않은 가짜(UNKNOWN)는 OCR 단계에서 이미 FAIL이라 '문서 미인식'으로 따로 센다", ""]
    out += ["| 구분 | 종류 | 장수 | 문서 미인식 | OCR status OK | suspicious | 얼굴 없음 | 비율 이상 | 무채색 바탕 |",
            "|---|---|---|---|---|---|---|---|---|"]
    groups = defaultdict(list)
    for r in rows:
        groups[(r["label"], r["kind"])].append(r)
    for (label, kind), rs in sorted(groups.items()):
        checked = [r for r in rs if r["checks"]]
        n = len(rs)

        def reason(code):
            return pct(sum(code in r["checks"]["reasons"] for r in checked), len(checked))

        out.append(f"| {'진짜' if label == 'genuine' else '가짜'} | {kind} | {n} | "
                   f"{pct(sum(r['checks'] is None for r in rs), n)} | {pct(sum(r['status'] == 'OK' for r in rs), n)} | "
                   f"**{pct(sum(r['checks']['suspicious'] for r in checked), len(checked))}** | "
                   f"{reason('NO_FACE_IN_PHOTO_AREA')} | {reason('CARD_ASPECT')} | {reason('PLAIN_BACKGROUND')} |")
    out += ["", "## 조건별 (가짜 중 OCR status OK인데 suspicious 아님 = 놓친 위험한 경우)", ""]
    missed = [r for r in rows if r["label"] == "fake" and r["status"] == "OK" and r["checks"]
              and not r["checks"]["suspicious"]]
    out.append(f"- 놓친 가짜: {len(missed)}장")
    for r in missed[:20]:
        out.append(f"  - {r['kind']}/{r['condition']}: {r['image']} {json.dumps(r['checks'], ensure_ascii=False)}")
    false_pos = [r for r in rows if r["label"] == "genuine" and r["checks"] and r["checks"]["suspicious"]]
    out += ["", f"- 오탐한 진짜: {len(false_pos)}장"]
    for r in false_pos[:20]:
        out.append(f"  - {r['condition']}: {r['image']} {json.dumps(r['checks'], ensure_ascii=False)}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--genuine", nargs="*", type=Path, default=[])
    ap.add_argument("--fake", nargs="*", type=Path, default=[])
    ap.add_argument("--per-group", type=int, default=None, help="폴더(조건)·문서 종류마다 최대 장수")
    ap.add_argument("--out", type=Path, default=ROOT / "samples" / "eval" / "checks")
    args = ap.parse_args(argv)

    items = collect(args.genuine, "genuine", args.per_group) + collect(args.fake, "fake", args.per_group)
    rows = run(items, Settings())
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (args.out / "report.md").write_text(summarize(rows), encoding="utf-8")
    print(f"{len(rows)}장 → {args.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
