import logging
import threading

import pytest
from fastapi.testclient import TestClient

from idocr.config import Settings
from idocr.ocr.engine import EnginePool, ModelInfo, OcrLine
from idocr.service.app import create_app
from tests.conftest import make_image

FAKE_MODELS = ModelInfo(det="det.onnx@sha256:aaa", rec="rec.onnx@sha256:bbb", cls=None)


class FakeEngine:
    def __init__(self, behavior=None):
        self.behavior = behavior
        self.calls = 0

    def run(self, bgr, scale=1.0):
        self.calls += 1
        if self.behavior:
            return self.behavior()
        return [OcrLine(text="주민등록증", score=0.99, box=[[0, 0], [10, 0], [10, 5], [0, 5]])]


def make_client(behavior=None, **overrides) -> TestClient:
    settings = Settings(enable_raw_endpoint=True, ocr_workers=1, **overrides)
    app = create_app(
        settings,
        pool_factory=lambda s: EnginePool([FakeEngine(behavior)]),
        model_info_factory=lambda s: FAKE_MODELS,
    )
    return TestClient(app)


def post_image(client, data, content_type="image/jpeg"):
    return client.post("/v1/ocr/raw", content=data, headers={"Content-Type": content_type})


def test_health_and_ready():
    with make_client() as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ready"}


def test_raw_ocr_returns_lines(jpeg_bytes):
    with make_client() as client:
        r = post_image(client, jpeg_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["lines"][0]["text"] == "주민등록증"
    assert body["image"] == {"width": 320, "height": 200, "scale": 1.0, "exif_rotated": False}
    assert body["model"]["rec"] == "rec.onnx@sha256:bbb"
    assert len(body["request_id"]) == 32


def test_raw_endpoint_disabled_by_default(jpeg_bytes):
    settings = Settings(ocr_workers=1)
    app = create_app(settings, pool_factory=lambda s: EnginePool([FakeEngine()]),
                     model_info_factory=lambda s: FAKE_MODELS)
    with TestClient(app) as client:
        r = post_image(client, jpeg_bytes)
    assert r.status_code == 404
    assert r.json()["error"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "data,content_type,status,code",
    [
        (b"x", "text/plain", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"", "image/jpeg", 400, "EMPTY_BODY"),
        (b"not an image", "image/jpeg", 400, "IMAGE_DECODE_ERROR"),
    ],
)
def test_input_errors(data, content_type, status, code):
    with make_client() as client:
        r = post_image(client, data, content_type)
    assert r.status_code == status
    assert r.json()["error"] == code


def test_payload_too_large():
    with make_client(max_image_bytes=1000) as client:
        r = post_image(client, make_image((800, 800), fmt="PNG", color=(1, 2, 3)) + b"\0" * 2000)
    assert r.status_code == 413
    assert r.json()["error"] == "PAYLOAD_TOO_LARGE"


def test_busy_when_queue_full(jpeg_bytes):
    release = threading.Event()
    entered = threading.Event()

    def slow():
        entered.set()
        release.wait(5)
        return []

    with make_client(behavior=slow, queue_limit=1) as client:
        results = {}
        t = threading.Thread(target=lambda: results.setdefault("first", post_image(client, jpeg_bytes)))
        t.start()
        assert entered.wait(5)
        second = post_image(client, jpeg_bytes)
        release.set()
        t.join(5)
    assert second.status_code == 503
    assert second.json()["error"] == "BUSY"
    assert results["first"].status_code == 200


def test_timeout(jpeg_bytes):
    release = threading.Event()

    def slow():
        release.wait(5)
        return []

    with make_client(behavior=slow, request_timeout_s=0.2) as client:
        r = post_image(client, jpeg_bytes)
        release.set()
    assert r.status_code == 504
    assert r.json()["error"] == "TIMEOUT"


def test_internal_error_does_not_leak(jpeg_bytes, caplog):
    def boom():
        raise RuntimeError("ocr text 900101-1234567")

    with caplog.at_level(logging.DEBUG):
        with make_client(behavior=boom) as client:
            r = post_image(client, jpeg_bytes)
    assert r.status_code == 500
    assert r.json()["error"] == "INTERNAL"
    assert "1234567" not in r.text
    assert "1234567" not in caplog.text
    assert "RuntimeError" in caplog.text


class SpecimenEngine(FakeEngine):
    def run(self, bgr, scale=1.0):
        from tests.unit.test_resident_card import SPECIMEN
        return list(SPECIMEN)

    def recognize(self, crop):
        return "홍길동", 0.93


def make_id_client(engine, **overrides) -> TestClient:
    settings = Settings(ocr_workers=1, **overrides)
    app = create_app(settings, pool_factory=lambda s: EnginePool([engine]), model_info_factory=lambda s: FAKE_MODELS)
    return TestClient(app)


def post_id(client, data, content_type="image/jpeg"):
    return client.post("/v1/ocr/id", content=data, headers={"Content-Type": content_type})


def test_id_endpoint_structured_result():
    with make_id_client(SpecimenEngine()) as client:
        r = post_id(client, make_image((1573, 1000)))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OK"
    assert body["document_type"] == "RESIDENT_CARD"
    assert body["fields"]["name"] == "홍길동"
    assert body["fields"]["rrn"] == "800101-2345678"
    assert body["field_meta"]["rrn"]["accepted"] is True
    assert body["model"]["schema"] == "1.0"
    assert len(body["request_id"]) == 32 and body["elapsed_ms"] >= 0


def test_id_endpoint_available_when_raw_disabled():
    with make_id_client(SpecimenEngine(), enable_raw_endpoint=False) as client:
        assert post_id(client, make_image()).status_code == 200


def test_id_endpoint_masks_rrn_when_configured():
    with make_id_client(SpecimenEngine(), rrn_output="masked") as client:
        body = post_id(client, make_image((1573, 1000))).json()
    assert body["fields"]["rrn"] == "800101-2******"


def test_id_endpoint_decode_error_is_fail_envelope():
    with make_id_client(SpecimenEngine()) as client:
        r = post_id(client, b"not an image")
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["fail_reason"]) == ("FAIL", "IMAGE_DECODE_ERROR")


def test_id_endpoint_does_not_log_field_values(caplog):
    with caplog.at_level(logging.DEBUG):
        with make_id_client(SpecimenEngine()) as client:
            post_id(client, make_image((1573, 1000)))
    assert "2345678" not in caplog.text
    assert "홍길동" not in caplog.text
