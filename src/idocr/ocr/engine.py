"""RapidOCR 래퍼.

rapidocr 3.9.2 기본값은 PP-OCRv6(한국어 미지원)이므로 모델 경로를 항상 명시한다.
경로가 없으면 rapidocr가 외부에서 모델을 받으려 하므로, 생성 전에 파일 존재를 먼저 확인한다.
"""

import hashlib
import queue
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

from idocr.config import Settings


class ModelFilesMissing(Exception):
    pass


class ModelCharsetError(Exception):
    pass


@dataclass(frozen=True)
class OcrLine:
    text: str
    score: float
    box: list[list[float]]  # 4점 [[x, y], ...], 축소 전 원본 좌표


@dataclass(frozen=True)
class ModelInfo:
    det: str
    rec: str
    cls: str | None


def _file_id(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path.name}@sha256:{h[:12]}"


def _has_embedded_charset(rec_path: Path) -> bool:
    import onnxruntime as ort

    sess = ort.InferenceSession(str(rec_path), providers=["CPUExecutionProvider"])
    return "character" in sess.get_modelmeta().custom_metadata_map


def required_files(settings: Settings) -> dict[str, Path]:
    files = {
        "det": settings.model_path(settings.det_model),
        "rec": settings.model_path(settings.rec_model),
        "cls": settings.model_path(settings.cls_model),
    }
    keys = settings.model_path(settings.rec_keys)
    if keys.exists():
        files["rec_keys"] = keys
    return files


def build_params(settings: Settings) -> dict:
    files = required_files(settings)
    params = {
        "Global.log_level": "error",
        "Global.use_cls": settings.use_cls,
        "Global.max_side_len": settings.max_side_len,
        "Det.model_path": str(files["det"]),
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        "Rec.model_path": str(files["rec"]),
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.KOREAN,
        # cls는 use_cls=False여도 생성되므로 경로를 항상 넘긴다
        "Cls.model_path": str(files["cls"]),
        "EngineConfig.onnxruntime.intra_op_num_threads": settings.ort_intra_threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }
    if "rec_keys" in files:
        params["Rec.rec_keys_path"] = str(files["rec_keys"])
    return params


class OcrEngine:
    """RapidOCR 인스턴스 하나. 호출마다 내부 상태를 갱신하므로 스레드 간 공유하지 않는다 (EnginePool 사용)."""

    def __init__(self, settings: Settings):
        files = required_files(settings)
        missing = [k for k, p in files.items() if not p.exists()]
        if not missing and "rec_keys" not in files and not _has_embedded_charset(files["rec"]):
            missing.append("rec_keys")  # 없으면 rapidocr가 사전을 외부에서 받으려 함
        if missing:
            raise ModelFilesMissing(", ".join(missing))
        self._ocr = RapidOCR(params=build_params(settings))
        if settings.require_hangul and not self.has_hangul():
            raise ModelCharsetError("recognition model charset has no Hangul")

    @property
    def charset(self) -> list[str]:
        return list(self._ocr.text_rec.postprocess_op.character)

    def has_hangul(self) -> bool:
        return any("가" <= c <= "힣" for c in self.charset)

    def run(self, bgr: np.ndarray, scale: float = 1.0) -> list[OcrLine]:
        out = self._ocr(bgr)
        if out is None or out.txts is None or out.boxes is None:
            return []
        inv = 1.0 / scale if scale else 1.0
        lines = []
        scores = out.scores if out.scores is not None else [0.0] * len(out.txts)
        for text, score, box in zip(out.txts, scores, out.boxes):
            pts = [[round(float(x) * inv, 1), round(float(y) * inv, 1)] for x, y in np.asarray(box).tolist()]
            lines.append(OcrLine(text=str(text), score=round(float(score), 4), box=pts))
        return lines


def model_info(settings: Settings) -> ModelInfo:
    files = required_files(settings)
    return ModelInfo(
        det=_file_id(files["det"]),
        rec=_file_id(files["rec"]),
        cls=_file_id(files["cls"]) if settings.use_cls else None,
    )


class EnginePool:
    def __init__(self, engines: list):
        self._q: queue.Queue = queue.Queue()
        for e in engines:
            self._q.put(e)
        self.size = len(engines)

    @classmethod
    def create(cls, settings: Settings) -> "EnginePool":
        return cls([OcrEngine(settings) for _ in range(settings.ocr_workers)])

    @contextmanager
    def acquire(self) -> Iterator[OcrEngine]:
        engine = self._q.get()
        try:
            yield engine
        finally:
            self._q.put(engine)
