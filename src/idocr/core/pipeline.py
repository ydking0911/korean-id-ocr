"""analyze(): 전처리된 이미지 → OCR → 문서 판별 → 필드 추출 → 판정.

결과가 OK가 아니면 대비 보정·90°·270°·180° 회전으로 다시 시도하고, 가장 좋은 결과를 돌려준다.
시도 순서는 첫 결과로 정한다: 문서를 못 알아보면 회전 먼저, 제목이 아래쪽에 있으면(뒤집힘) 180° 먼저.
"""

from dataclasses import dataclass
from datetime import date
from typing import Callable

import cv2
import numpy as np

from idocr.core import judge
from idocr.core.classify import classify
from idocr.core.extract import resident_card
from idocr.core.layout import to_lines
from idocr.core.result import DocumentType, Extraction, FailReason, IdDocumentResult, Quad, Status
from idocr.ocr.preprocess import PreparedImage


@dataclass(frozen=True)
class Pass:
    name: str
    rotation: int  # 시계 방향 회전 각도
    contrast: bool


ORIGINAL = Pass("original", 0, False)
CONTRAST = Pass("contrast", 0, True)
ROT90 = Pass("rot90", 90, False)
ROT270 = Pass("rot270", 270, False)
ROT180 = Pass("rot180", 180, False)  # 뒤집힌 사진: 줄 방향 분류(cls)로 글자는 읽히지만 위아래 배치가 반대


def _retry_order(first: "_Attempt") -> tuple[Pass, ...]:
    if first.vertical:
        return (ROT90, ROT270, CONTRAST, ROT180)
    if first.doc_type == DocumentType.UNKNOWN:
        return (ROT90, ROT270, ROT180, CONTRAST)
    if first.title_low:
        return (ROT180, CONTRAST, ROT90, ROT270)
    return (CONTRAST, ROT90, ROT270, ROT180)


@dataclass
class _Attempt:
    pass_: Pass
    doc_type: DocumentType
    extraction: Extraction | None
    n_lines: int
    inverse: Callable[[Quad], Quad]
    title_low: bool = False  # 제목이 줄들의 아래쪽 절반에 있음 → 뒤집힌 사진 신호
    vertical: bool = False  # 박스 대부분이 세로로 김 → 90°/270° 누운 사진 신호


def analyze(prepared: PreparedImage, engine, thresholds: judge.Thresholds,
            mask_rrn: bool = False, today: date | None = None) -> IdDocumentResult:
    first = best = _run_pass(prepared.bgr, ORIGINAL, engine, today)
    passes_run = 1
    for p in _retry_order(first):
        if best.extraction is not None:
            if judge.decide(best.extraction, judge.SPECS[best.doc_type], thresholds)[0] == Status.OK:
                break
        elif best.doc_type != DocumentType.UNKNOWN:
            break  # 문서 종류는 알아냈지만 추출기가 없음 → 재시도해도 결과가 같다
        passes_run += 1
        attempt = _run_pass(prepared.bgr, p, engine, today)
        if _rank(attempt, thresholds) > _rank(best, thresholds):
            best = attempt

    preprocess = {
        "exif_rotated": prepared.exif_rotated,
        "scale": round(prepared.scale, 4),
        "rotation": best.pass_.rotation,
        "contrast_enhanced": best.pass_.contrast,
        "passes": passes_run,
    }
    if best.n_lines == 0:
        return judge.failure(FailReason.NO_TEXT, preprocess)
    if best.extraction is None:
        warnings = ["NOT_IMPLEMENTED:DRIVER_LICENSE"] if best.doc_type == DocumentType.DRIVER_LICENSE else []
        return judge.failure(FailReason.UNSUPPORTED_DOCUMENT, preprocess, best.doc_type, warnings)

    inv_scale = 1.0 / prepared.scale

    def to_original(q: Quad) -> Quad:
        return [[round(x * inv_scale, 1), round(y * inv_scale, 1)] for x, y in best.inverse(q)]

    return judge.assemble(best.extraction, thresholds, to_original, preprocess, mask_rrn=mask_rrn)


def _rank(a: _Attempt, th: judge.Thresholds) -> tuple:
    spec = judge.SPECS.get(a.doc_type)
    base = judge.rank(a.extraction, spec, th)
    # 추출기가 없는 문서라도 문서로 인식했으면 아무것도 못 찾은 것보다 낫다. 동률이면 먼저 시도한 패스 유지
    return base + (a.doc_type != DocumentType.UNKNOWN,)


def _run_pass(bgr: np.ndarray, p: Pass, engine, today) -> _Attempt:
    img = enhance_contrast(bgr) if p.contrast else bgr
    img, inverse = rotate(img, p.rotation)
    lines = to_lines(engine.run(img))
    doc_type, title = classify(lines)

    extraction = None
    if doc_type == DocumentType.RESIDENT_CARD:
        def recognize(q: Quad):
            crop = crop_quad(img, q)
            return engine.recognize(crop) if crop is not None else ("", 0.0)
        extraction = resident_card.extract(lines, title, recognize, today)
    title_low = title is not None and len(lines) >= 3 and title.cy > sorted(l.cy for l in lines)[len(lines) // 2]
    long_boxes = [l for l in lines if len(l.text) >= 3]
    vertical = bool(long_boxes) and sum(l.h > 1.5 * (l.x1 - l.x0) for l in long_boxes) > len(long_boxes) / 2
    return _Attempt(p, doc_type, extraction, len(lines), inverse, title_low, vertical)


def enhance_contrast(bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def rotate(bgr: np.ndarray, degrees: int) -> tuple[np.ndarray, Callable[[Quad], Quad]]:
    """시계 방향 회전한 이미지와, 회전 좌표 → 원래 좌표 변환 함수."""
    h, w = bgr.shape[:2]
    if degrees == 0:
        return bgr, lambda q: q
    if degrees == 90:
        # (x, y) → (h-1-y, x)  ⇒  역변환 (x', y') → (y', h-1-x')
        return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE), lambda q: [[y, h - 1 - x] for x, y in q]
    if degrees == 270:
        # (x, y) → (y, w-1-x)  ⇒  역변환 (x', y') → (w-1-y', x')
        return cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE), lambda q: [[w - 1 - y, x] for x, y in q]
    if degrees == 180:
        # (x, y) → (w-1-x, h-1-y), 자기 자신이 역변환
        return cv2.rotate(bgr, cv2.ROTATE_180), lambda q: [[w - 1 - x, h - 1 - y] for x, y in q]
    raise ValueError(degrees)


def crop_quad(bgr: np.ndarray, q: Quad) -> np.ndarray | None:
    h, w = bgr.shape[:2]
    x0 = max(0, int(min(p[0] for p in q)))
    x1 = min(w, int(max(p[0] for p in q)) + 1)
    y0 = max(0, int(min(p[1] for p in q)))
    y1 = min(h, int(max(p[1] for p in q)) + 1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return np.ascontiguousarray(bgr[y0:y1, x0:x1])
