"""모델 파일을 받아 SHA256을 검증한다. 표준 라이브러리만 사용 (호스트에서 바로 실행 가능).

    python scripts/download_models.py                 # default 프로필 다운로드
    python scripts/download_models.py --profile compare
    python scripts/download_models.py --verify-only   # Docker 빌드 시 검증용
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "models" / "manifest.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_entries(manifest: dict, profiles: list[str]) -> list[tuple[str, dict]]:
    keys: list[str] = []
    for profile in profiles:
        if profile not in manifest["profiles"]:
            raise SystemExit(f"알 수 없는 프로필: {profile}")
        keys += [k for k in manifest["profiles"][profile] if k not in keys]
    return [(k, manifest["files"][k]) for k in keys]


def check_file(path: Path, expected: str | None) -> tuple[bool, str]:
    """(통과 여부, 실제 해시). 기대 해시가 없으면 존재만 확인한다."""
    actual = sha256_of(path)
    return (expected is None or actual == expected), actual


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 같은 디렉터리에 임시 파일로 받은 뒤 원자적으로 교체
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=60) as resp:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dest", type=Path, default=None, help="저장 위치 (기본: manifest와 같은 디렉터리)")
    parser.add_argument("--profile", action="append", default=None, help="여러 번 지정 가능 (기본: default)")
    parser.add_argument("--base-url", default=None, help="미러 주소로 교체")
    parser.add_argument("--verify-only", action="store_true", help="다운로드 없이 존재·해시만 검증")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 받기")
    parser.add_argument("--strict", action="store_true", help="manifest에 해시가 없는 파일도 실패 처리")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    dest_dir = args.dest or args.manifest.parent
    base_url = args.base_url or manifest["base_url"]
    entries = resolve_entries(manifest, args.profile or ["default"])

    failed = False
    for key, entry in entries:
        path = dest_dir / Path(entry["path"]).name
        expected = entry.get("sha256")

        if not args.verify_only and (args.force or not path.exists()):
            print(f"[download] {key} <- {entry['path']}")
            try:
                download(base_url + entry["path"], path)
            except OSError as e:
                print(f"[error] {key}: 다운로드 실패 ({type(e).__name__}: {e})", file=sys.stderr)
                failed = True
                continue

        if not path.exists():
            print(f"[missing] {key}: {path}", file=sys.stderr)
            failed = True
            continue

        ok, actual = check_file(path, expected)
        if not ok:
            print(f"[mismatch] {key}: expected {expected}, got {actual}", file=sys.stderr)
            failed = True
        elif expected is None:
            print(f"[unpinned] {key}: sha256 {actual} (manifest에 기록 권장)")
            failed = failed or args.strict
        else:
            print(f"[ok] {key}: {path.name}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
