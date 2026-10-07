"""평가 하네스: 정답이 있는 이미지 세트로 파이프라인 정확도·오채택·조건별 성능·임계값을 측정한다.

    python -m tools.evaluate --data samples/synthetic --out samples/eval/run1
    python -m tools.evaluate --data samples/synthetic --specimen   # 견본(samples/specimen)도 포함

결과: <out>/report.md (요약), <out>/results.jsonl (이미지별 상세). 실물 이미지 결과는 커밋하지 않는다.
"""

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from idocr.config import Settings
from idocr.core.judge import SPECS, Thresholds
from idocr.core.pipeline import analyze
from idocr.core.result import DocumentType
from idocr.ocr.engine import EnginePool
from idocr.ocr.preprocess import ImageDecodeError, prepare

ROOT = Path(__file__).resolve().parents[1]
EXTRA_FIELDS = {"DRIVER_LICENSE": ("serial_code",)}
TARGET_PRECISION = 0.98


# ── 비교 ────────────────────────────────────────────────

def norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        return f"{v.get('start')}~{v.get('end')}"
    if isinstance(v, list):
        return "|".join(norm(x) for x in v)
    return "".join(str(v).split())


def cer(pred, gt) -> float:
    a, b = norm(pred), norm(gt)
    if not b:
        return 0.0 if not a else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return min(1.0, prev[-1] / len(b))


def eval_fields(doc_type: str) -> tuple[str, ...]:
    spec = SPECS[DocumentType(doc_type)]
    return spec.required + EXTRA_FIELDS.get(doc_type, ())


def score(result: dict, gt: dict) -> dict:
    doc = gt["document_type"]
    out = {}
    for key in eval_fields(doc):
        pred = (result.get("fields") or {}).get(key)
        meta = (result.get("field_meta") or {}).get(key) or {}
        g = gt["fields"].get(key)
        out[key] = {
            "pred": pred, "gt": g,
            "found": pred is not None,
            "exact": pred == g,
            "correct": norm(pred) == norm(g),  # 띄어쓰기 무시
            "cer": cer(pred, g),
            "confidence": meta.get("confidence"),
            "accepted": bool(meta.get("accepted")),
        }
    return out


# ── 실행 ────────────────────────────────────────────────

def load_items(data: Path | None, specimen: bool) -> list[dict]:
    items = []
    if data is not None:
        for line in (data / "index.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            items.append({"image": data / row["image"], "gt": data / row["gt"], "condition": row["condition"]})
    if specimen:
        sdir = ROOT / "samples" / "specimen"
        for gt in sorted(sdir.glob("*.gt.json")):
            img = next((p for p in sdir.glob(gt.name.replace(".gt.json", "") + ".*") if not p.name.endswith(".json")), None)
            if img:
                items.append({"image": img, "gt": gt, "condition": "specimen"})
    return items


def run(items: list[dict], settings: Settings) -> list[dict]:
    pool = EnginePool.create(settings)
    th = Thresholds(settings.threshold_numeric, settings.threshold_text, settings.threshold_address)

    def one(item):
        gt = json.loads(Path(item["gt"]).read_text(encoding="utf-8"))
        data = Path(item["image"]).read_bytes()
        started = time.perf_counter()
        try:
            prepared = prepare(data, max_side_len=settings.max_side_len, max_pixels=settings.max_image_pixels,
                               min_side_len=settings.min_side_len)
            with pool.acquire() as engine:
                result = analyze(prepared, engine, th).to_dict()
        except ImageDecodeError:
            result = {"status": "FAIL", "fail_reason": "IMAGE_DECODE_ERROR", "fields": {}, "field_meta": {}}
        ms = (time.perf_counter() - started) * 1000
        return {
            "image": str(Path(item["image"]).relative_to(ROOT)) if Path(item["image"]).is_relative_to(ROOT) else str(item["image"]),
            "condition": item["condition"],
            "document_type": gt["document_type"],
            "predicted_type": result.get("document_type"),
            "status": result["status"],
            "fail_reason": result.get("fail_reason"),
            "passes": (result.get("preprocess") or {}).get("passes"),
            "elapsed_ms": round(ms),
            "fields": score(result, gt) if result.get("document_type") == gt["document_type"] else {},
            "core": list(SPECS[DocumentType(gt["document_type"])].core),
        }

    with ThreadPoolExecutor(max_workers=pool.size) as ex:
        return list(ex.map(one, items))


# ── 집계 ────────────────────────────────────────────────

def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def summarize(rows: list[dict], th: Thresholds) -> str:
    out = ["# 평가 리포트", ""]
    docs = sorted({r["document_type"] for r in rows})
    lat = [r["elapsed_ms"] for r in rows]
    out += [f"- 이미지 {len(rows)}장 · 지연 p50 {statistics.median(lat):.0f}ms · p95 "
            f"{sorted(lat)[int(0.95 * (len(lat) - 1))]:.0f}ms",
            f"- 임계값: numeric {th.numeric} / text {th.text} / address {th.address}", ""]

    for doc in docs:
        rs = [r for r in rows if r["document_type"] == doc]
        fields = eval_fields(doc)
        status = Counter(r["status"] for r in rs)
        all_ok = sum(bool(r["fields"]) and all(r["fields"][k]["correct"] for k in fields) for r in rs)
        false_ok = sum(r["status"] == "OK" and any(f["accepted"] and not f["correct"] for f in r["fields"].values())
                       for r in rs)
        wrong_type = sum(r["predicted_type"] != doc for r in rs)
        out += [f"## {doc} ({len(rs)}장)", "",
                "| 지표 | 값 |", "|---|---|",
                f"| status OK / PARTIAL / FAIL | {pct(status['OK'], len(rs))} / {pct(status['PARTIAL'], len(rs))} / "
                f"{pct(status['FAIL'], len(rs))} |",
                f"| 문서 종류 오판 | {wrong_type} |",
                f"| 평가 필드 전부 정답 (띄어쓰기 무시) | {pct(all_ok, len(rs))} |",
                f"| **OK인데 채택 필드 중 오답 있음** | {false_ok} ({pct(false_ok, len(rs))}) |", ""]

        out += ["| 필드 | 검출 | 정답(공백무시) | 정답(완전일치) | 평균 CER | 채택률 | 채택 정밀도 | 오채택 |",
                "|---|---|---|---|---|---|---|---|"]
        for k in fields:
            fs = [r["fields"][k] for r in rs if r["fields"]]
            n = len(rs)
            acc = [f for f in fs if f["accepted"]]
            out.append(
                f"| {k} | {pct(sum(f['found'] for f in fs), n)} | {pct(sum(f['correct'] for f in fs), n)} | "
                f"{pct(sum(f['exact'] for f in fs), n)} | {statistics.mean([f['cer'] for f in fs] or [1]):.3f} | "
                f"{pct(len(acc), n)} | {pct(sum(f['correct'] for f in acc), len(acc))} | "
                f"{sum(not f['correct'] for f in acc)} |")
        out.append("")

        out += ["| 조건 | 장수 | OK | 핵심 필드 정답 | 전부 정답 | 지연 p50 |", "|---|---|---|---|---|---|"]
        for cond in sorted({r["condition"] for r in rs}):
            cs = [r for r in rs if r["condition"] == cond]
            core_ok = sum(bool(r["fields"]) and all(r["fields"][k]["correct"] for k in r["core"]) for r in cs)
            all_c = sum(bool(r["fields"]) and all(r["fields"][k]["correct"] for k in fields) for r in cs)
            out.append(f"| {cond} | {len(cs)} | {pct(sum(r['status'] == 'OK' for r in cs), len(cs))} | "
                       f"{pct(core_ok, len(cs))} | {pct(all_c, len(cs))} | "
                       f"{statistics.median([r['elapsed_ms'] for r in cs]):.0f}ms |")
        out.append("")

        out += ["<details><summary>오답 예시</summary>", ""]
        for k in fields:
            bad = [r["fields"][k] for r in rs if r["fields"] and r["fields"][k]["found"] and not r["fields"][k]["correct"]]
            for f in bad[:4]:
                out.append(f"- `{k}` 예측 `{f['pred']}` / 정답 `{f['gt']}` (conf {f['confidence']}, "
                           f"{'채택' if f['accepted'] else '미채택'})")
        out += ["", "</details>", ""]

    out += calibration(rows)
    return "\n".join(out)


def calibration(rows: list[dict]) -> list[str]:
    """종류별로 '신뢰도 ≥ t 인 값의 정답률'과 채택 비율. 목표 정밀도를 만족하는 가장 낮은 t를 추천."""
    kinds = defaultdict(list)
    for r in rows:
        spec = SPECS[DocumentType(r["document_type"])]
        for k, f in r["fields"].items():
            kind = spec.kinds.get(k)
            if kind and f["found"] and f["confidence"] is not None:
                kinds[kind].append((f["confidence"], f["correct"]))
    out = ["## 신뢰도 임계값 보정", "",
           f"목표: 채택한 값의 정답률(정밀도) ≥ {TARGET_PRECISION:.0%}. 커버리지 = 검출된 값 중 채택되는 비율.", "",
           "| 종류 | 표본 | 임계값 | 정밀도 | 커버리지 |", "|---|---|---|---|---|"]
    for kind, pairs in sorted(kinds.items()):
        best = None
        for t in [x / 100 for x in range(50, 100)]:
            acc = [c for conf, c in pairs if conf >= t]
            if not acc:
                continue
            prec = sum(acc) / len(acc)
            mark = ""
            if best is None and prec >= TARGET_PRECISION:
                best = t
                mark = " ← 추천"
            if t in (0.5, 0.7, 0.8, 0.85, 0.9, 0.95) or mark:
                out.append(f"| {kind} | {len(pairs)} | {t:.2f} | {prec:.1%} | {len(acc) / len(pairs):.1%}{mark} |")
        if best is None:
            out.append(f"| {kind} | {len(pairs)} | - | 목표 미달 (임계값으로 해결 불가) | - |")
    return out + [""]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "samples" / "synthetic")
    ap.add_argument("--specimen", action="store_true", help="samples/specimen 견본도 포함")
    ap.add_argument("--out", type=Path, default=ROOT / "samples" / "eval" / "latest")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args(argv)

    settings = Settings(ocr_workers=args.workers, ort_intra_threads=args.threads)
    items = load_items(args.data if args.data.exists() else None, args.specimen)
    if not items:
        raise SystemExit("평가할 이미지가 없음 (tools.synth.generate 먼저 실행)")
    started = time.perf_counter()
    rows = run(items, settings)
    th = Thresholds(settings.threshold_numeric, settings.threshold_text, settings.threshold_address)
    report = summarize(rows, th)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(report, encoding="utf-8")
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(report)
    print(f"\n{len(rows)}장, {time.perf_counter() - started:.0f}초 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
