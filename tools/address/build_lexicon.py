"""행정구역 이름 사전(src/idocr/data/admin_names.json) 생성.

원자료: vuski/admdongkor (CC BY 4.0, https://github.com/vuski/admdongkor) — 1975년 이후 시·도·시군구·읍면동 이름 이력.
오래된 신분증의 옛 지명(예: 부산직할시, 강원도)도 교정할 수 있게 전체 기간의 이름을 넣는다.

    git clone --depth 1 --filter=blob:none --sparse https://github.com/vuski/admdongkor /tmp/admdongkor
    (cd /tmp/admdongkor && git sparse-checkout set --no-cone '/dist/data/timeline_v3_*.parquet')
    pip install pyarrow
    python -m tools.address.build_lexicon /tmp/admdongkor
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "src" / "idocr" / "data" / "admin_names.json"


def split_sgg(name: str) -> list[str]:
    """'수원시장안구' → ['수원시', '장안구'] (일반구가 있는 시)."""
    m = re.fullmatch(r"(.+?시)(.+구)", name)
    return [m.group(1), m.group(2)] if m else [name]


def main(argv=None) -> int:
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser()
    ap.add_argument("admdongkor", type=Path)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    data = args.admdongkor / "dist" / "data"

    sido: set[str] = set()
    sgg: dict[str, set[str]] = defaultdict(set)
    for r in pq.read_table(data / "timeline_v3_sgg.parquet", columns=["name", "sidonm"]).to_pylist():
        sido.add(r["sidonm"])
        for part in split_sgg(r["name"]):
            sgg[r["sidonm"]].add(part)
    emd = {r["name"] for r in pq.read_table(data / "timeline_v3_emd.parquet", columns=["name"]).to_pylist()}

    out = {
        "source": "vuski/admdongkor timeline_v3 (CC BY 4.0)",
        "sido": sorted(sido),
        "sgg": {k: sorted(v) for k, v in sorted(sgg.items())},
        "emd": sorted(emd),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"sido {len(sido)}, sgg {sum(len(v) for v in sgg.values())}, emd {len(emd)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
