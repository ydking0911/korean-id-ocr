import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import download_models  # noqa: E402


def setup_source(tmp_path, files: dict[str, bytes], pins: dict[str, str | None]) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    for name, data in files.items():
        (src / name).write_bytes(data)
    manifest = {
        "base_url": src.as_uri() + "/",
        "profiles": {"default": list(pins)},
        "files": {k: {"path": k, "sha256": v} for k, v in pins.items()},
    }
    mpath = tmp_path / "models" / "manifest.json"
    mpath.parent.mkdir()
    mpath.write_text(json.dumps(manifest))
    return mpath


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_downloads_and_verifies(tmp_path):
    m = setup_source(tmp_path, {"a.onnx": b"aaa"}, {"a.onnx": sha(b"aaa")})
    assert download_models.main(["--manifest", str(m)]) == 0
    assert (m.parent / "a.onnx").read_bytes() == b"aaa"
    assert download_models.main(["--manifest", str(m), "--verify-only"]) == 0


def test_hash_mismatch_fails(tmp_path):
    m = setup_source(tmp_path, {"a.onnx": b"aaa"}, {"a.onnx": sha(b"other")})
    assert download_models.main(["--manifest", str(m)]) == 1


def test_missing_file_fails_verify(tmp_path):
    m = setup_source(tmp_path, {}, {"a.onnx": sha(b"aaa")})
    assert download_models.main(["--manifest", str(m), "--verify-only"]) == 1


def test_unpinned_passes_unless_strict(tmp_path, capsys):
    m = setup_source(tmp_path, {"dict.txt": b"x"}, {"dict.txt": None})
    assert download_models.main(["--manifest", str(m)]) == 0
    assert sha(b"x") in capsys.readouterr().out
    assert download_models.main(["--manifest", str(m), "--verify-only", "--strict"]) == 1


def test_failed_download_leaves_no_partial_file(tmp_path):
    m = setup_source(tmp_path, {}, {"a.onnx": sha(b"aaa")})
    assert download_models.main(["--manifest", str(m)]) == 1
    assert list(m.parent.glob("*.part")) == []
    assert not (m.parent / "a.onnx").exists()


def test_downloaded_file_is_world_readable(tmp_path):
    m = setup_source(tmp_path, {"a.onnx": b"aaa"}, {"a.onnx": sha(b"aaa")})
    assert download_models.main(["--manifest", str(m)]) == 0
    assert (m.parent / "a.onnx").stat().st_mode & 0o044 == 0o044
