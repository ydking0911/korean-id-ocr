"""OCR worker HTTP 서비스.

이미지는 multipart가 아닌 **요청 본문 그대로** 받는다. Starlette multipart는 1MB를 넘으면
임시 파일로 디스크에 쓰기 때문이다.

    uvicorn --factory idocr.service.app:create_app --host 0.0.0.0 --port 8000
    curl --data-binary @id.jpg -H "Content-Type: image/jpeg" http://127.0.0.1:8000/v1/ocr/raw
"""

import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from idocr.config import Settings, get_settings
from idocr.core import judge
from idocr.core.pipeline import analyze
from idocr.core.result import FailReason
from idocr.ocr.engine import EnginePool, ModelInfo, model_info
from idocr.ocr.preprocess import ImageDecodeError, prepare
from idocr.privacy.logging import safe_exc, setup_logging
from idocr.service.schemas import ErrorResponse, ImageMeta, OcrLineOut, RawOcrResponse

log = logging.getLogger("idocr.service")

SCHEMA_VERSION = "1.0"

ACCEPTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}


class ApiError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


class _Runtime:
    def __init__(self, settings: Settings, pool: EnginePool, models: ModelInfo):
        self.settings = settings
        self.pool = pool
        self.models = models
        self.executor = ThreadPoolExecutor(max_workers=pool.size, thread_name_prefix="ocr")
        self.in_flight = 0


def create_app(
    settings: Settings | None = None,
    pool_factory: Callable[[Settings], EnginePool] = EnginePool.create,
    model_info_factory: Callable[[Settings], ModelInfo] = model_info,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # uvicorn이 로깅을 구성한 뒤에 필터를 붙여야 uvicorn 핸들러에도 적용된다
        setup_logging(settings.log_level)
        pool = await asyncio.to_thread(pool_factory, settings)
        app.state.runtime = _Runtime(settings, pool, model_info_factory(settings))
        log.info("ready: workers=%d threads=%d", pool.size, settings.ort_intra_threads)
        try:
            yield
        finally:
            app.state.runtime.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="idocr", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _error(request, exc.status, exc.code)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        try:
            return await call_next(request)
        except Exception as e:
            # 서버 기본 핸들러까지 올라가면 트레이스백이 그대로 찍히므로 여기서 끊는다
            log.error("unhandled error: %s", safe_exc(e))
            return _error(request, 500, "INTERNAL")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request):
        if getattr(request.app.state, "runtime", None) is None:
            return JSONResponse({"status": "starting"}, status_code=503)
        return {"status": "ready"}

    @app.post(
        "/v1/ocr/raw",
        response_model=RawOcrResponse,
        responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse},
                   415: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
        summary="이미지 → 텍스트 줄 (개발 전용)",
    )
    async def ocr_raw(request: Request):
        if not settings.enable_raw_endpoint:
            raise ApiError(404, "NOT_FOUND")
        rt: _Runtime = request.app.state.runtime
        started = time.perf_counter()

        data = await _read_image_body(request, rt.settings.max_image_bytes)
        try:
            lines, prepared = await _run_job(rt, _raw_job, data)
        except ImageDecodeError:
            raise ApiError(400, "IMAGE_DECODE_ERROR") from None
        del data

        return RawOcrResponse(
            request_id=request.state.request_id,
            lines=[OcrLineOut(**asdict(line)) for line in lines],
            image=ImageMeta(
                width=prepared.original_size[0],
                height=prepared.original_size[1],
                scale=round(prepared.scale, 4),
                exif_rotated=prepared.exif_rotated,
            ),
            model=asdict(rt.models),
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )

    @app.post(
        "/v1/ocr/id",
        responses={413: {"model": ErrorResponse}, 415: {"model": ErrorResponse},
                   503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
        summary="신분증 이미지 → 구조화 JSON",
        description="응답 형식은 docs/05-output-schema.md. 이미지 디코딩 실패도 200 + status=FAIL로 응답한다.",
    )
    async def ocr_id(request: Request):
        rt: _Runtime = request.app.state.runtime
        started = time.perf_counter()

        data = await _read_image_body(request, rt.settings.max_image_bytes)
        try:
            result = await _run_job(rt, _id_job, data)
        except ImageDecodeError:
            result = judge.failure(FailReason.IMAGE_DECODE_ERROR, {})
        del data

        return {
            "request_id": request.state.request_id,
            **result.to_dict(),
            "model": {**asdict(rt.models), "schema": SCHEMA_VERSION},
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }

    return app


async def _read_image_body(request: Request, limit: int) -> bytes:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "PAYLOAD_TOO_LARGE")

    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise ApiError(413, "PAYLOAD_TOO_LARGE")
    if not buf:
        raise ApiError(400, "EMPTY_BODY")
    return bytes(buf)


async def _run_job(rt: _Runtime, job, data: bytes):
    if rt.in_flight >= rt.settings.queue_limit:
        raise ApiError(503, "BUSY")
    rt.in_flight += 1
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(rt.executor, job, rt, data)
        try:
            return await asyncio.wait_for(future, timeout=rt.settings.request_timeout_s)
        except asyncio.TimeoutError:
            raise ApiError(504, "TIMEOUT") from None
    finally:
        rt.in_flight -= 1


def _prepare(rt: _Runtime, data: bytes):
    return prepare(data, max_side_len=rt.settings.max_side_len, max_pixels=rt.settings.max_image_pixels)


def _raw_job(rt: _Runtime, data: bytes):
    prepared = _prepare(rt, data)
    with rt.pool.acquire() as engine:
        lines = engine.run(prepared.bgr, scale=prepared.scale)
    return lines, prepared


def _id_job(rt: _Runtime, data: bytes):
    prepared = _prepare(rt, data)
    s = rt.settings
    thresholds = judge.Thresholds(s.threshold_numeric, s.threshold_text, s.threshold_address)
    with rt.pool.acquire() as engine:
        return analyze(prepared, engine, thresholds, mask_rrn=s.rrn_output == "masked")


def _error(request: Request, status: int, code: str) -> JSONResponse:
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(ErrorResponse(request_id=rid, error=code).model_dump(), status_code=status)

