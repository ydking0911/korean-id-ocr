"""위조 의심 신호 (CPU). 판정이 아니라 관리자 수동 검증을 돕는 참고값이다.

잡으려는 것: 종이에 위치만 맞춰 쓴 글씨, 흑백 복사본, 사진 없는 출력물.
못 잡는 것: 견본을 편집해 컬러로 출력한 정교한 위조 → 공식 진위확인 조회가 필요하다 (docs/12).

신호
- face: 사진 영역에 얼굴 (주민등록증은 주민번호 줄 오른쪽, 운전면허증은 왼쪽)
- card_aspect: 카드 외곽선의 가로세로 비 (실물 85.6×54mm ≈ 1.586)
- background: 글자·얼굴을 뺀 바탕의 색감 (실물은 인쇄된 색 무늬가 있음, 흰 종이·흑백 복사는 거의 무채색)
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from idocr.core.result import DocumentType, Quad

CARD_RATIO = 85.6 / 54.0

# 임계값: 합성 진짜·가짜 개발 세트로 정하고 별도 세트로 확인 (docs/12)
RATIO_TOLERANCE = 0.10
MIN_COLORFULNESS = 12.0
FACE_HEIGHT_RANGE = (2.0, 12.0)  # 얼굴 높이 / 주민번호 줄 높이
MAX_CLIPPED = 0.5  # 바탕의 이 비율 이상이 하얗게 날아가면 색감 판정 보류
SATURATION_LIMIT = 110  # HSV S(0~255). 이보다 진한 픽셀(직인 등)은 바탕 색감 계산에서 뺀다


@dataclass
class Checks:
    face: dict | None = None
    card_aspect: dict | None = None
    background: dict | None = None
    reasons: list[str] = field(default_factory=list)
    inconclusive: list[str] = field(default_factory=list)  # 판단 못 한 신호 (관리자가 직접 볼 것)

    @property
    def suspicious(self) -> bool:
        return bool(self.reasons)

    def to_dict(self) -> dict:
        return {"suspicious": self.suspicious, "reasons": self.reasons, "inconclusive": self.inconclusive,
                "face": self.face, "card_aspect": self.card_aspect, "background": self.background}


def run(bgr: np.ndarray, doc_type: DocumentType, rrn_box: Quad | None, text_boxes: list[Quad],
        faces: list) -> Checks:
    c = Checks()
    quad = find_card_quad(bgr)

    c.face = _face_check(faces, doc_type, rrn_box)
    if c.face is None:
        c.inconclusive.append("FACE_NOT_CHECKED")  # 주민번호 줄을 못 찾아 사진 위치를 모름
    elif not c.face["ok"]:
        c.reasons.append("NO_FACE_IN_PHOTO_AREA")

    ratio, method = card_ratio(bgr, quad, text_boxes)
    if ratio is not None:
        # 외곽선이 보일 때만 판정한다. 이미지 틀 비율은 사용자가 잘라낸 사진(16:9 등)이면 의미가 없다
        ok = abs(ratio / CARD_RATIO - 1) <= RATIO_TOLERANCE if method == "contour" else None
        c.card_aspect = {"ratio": round(float(ratio), 3), "expected": round(CARD_RATIO, 3), "method": method, "ok": ok}
        if ok is False:
            c.reasons.append("CARD_ASPECT")
        elif ok is None:
            c.inconclusive.append("CARD_EDGES_NOT_VISIBLE")

    stats = background_stats(bgr, quad, text_boxes, faces)
    if stats is not None:
        color, brightness, clipped = stats
        # 하얗게 날아간 사진은 색을 잴 수 없다 → 판정 보류
        ok = None if clipped > MAX_CLIPPED else color >= MIN_COLORFULNESS
        c.background = {"colorfulness": round(color, 1), "min": MIN_COLORFULNESS, "brightness": round(brightness),
                        "clipped": round(clipped, 2), "ok": ok}
        if ok is False:
            c.reasons.append("PLAIN_BACKGROUND")
        elif ok is None:
            c.inconclusive.append("BACKGROUND_OVEREXPOSED")
    return c


# ── 얼굴 ────────────────────────────────────────────────

def _face_check(faces, doc_type: DocumentType, rrn_box: Quad | None) -> dict | None:
    if rrn_box is None:
        return None
    xs, ys = [p[0] for p in rrn_box], [p[1] for p in rrn_box]
    rx0, rx1, rh = min(xs), max(xs), max(ys) - min(ys)
    lo, hi = FACE_HEIGHT_RANGE
    for f in sorted(faces, key=lambda f: -f.score):
        side_ok = f.cx > rx1 if doc_type == DocumentType.RESIDENT_CARD else f.cx < rx0
        if side_ok and rh > 0 and lo <= f.h / rh <= hi:
            return {"found": True, "score": round(f.score, 3), "ok": True}
    return {"found": bool(faces), "score": round(max((f.score for f in faces), default=0.0), 3), "ok": False}


# ── 카드 외곽선 ──────────────────────────────────────────

def find_card_quad(bgr: np.ndarray) -> np.ndarray | None:
    """배경 위의 카드 외곽 사각형 (4점). 카드가 화면을 꽉 채우면 None."""
    h, w = bgr.shape[:2]
    s = 800 / max(h, w)
    small = cv2.resize(bgr, (round(w * s), round(h * s))) if s < 1 else bgr
    s = min(s, 1.0)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 30, 90), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = small.shape[0] * small.shape[1]
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        a = cv2.contourArea(cnt)
        if a < 0.15 * area or a > 0.97 * area:
            continue
        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return approx.reshape(4, 2).astype(np.float32) / s
    return None


def card_ratio(bgr: np.ndarray, quad: np.ndarray | None, text_boxes: list[Quad]) -> tuple[float | None, str]:
    if quad is not None:
        pts = _order(quad)
        top, right = np.linalg.norm(pts[1] - pts[0]), np.linalg.norm(pts[2] - pts[1])
        bottom, left = np.linalg.norm(pts[2] - pts[3]), np.linalg.norm(pts[3] - pts[0])
        w, h = (top + bottom) / 2, (left + right) / 2
        return (float(max(w, h) / min(w, h)) if min(w, h) > 0 else None), "contour"
    # 외곽선이 없으면 카드가 화면을 채운 것으로 보고 이미지 비율. 글자가 이미지 일부에만 있으면 판단 보류
    h, w = bgr.shape[:2]
    if text_boxes:
        xs = [p[0] for b in text_boxes for p in b]
        if (max(xs) - min(xs)) < 0.6 * w:
            return None, "frame"
    return max(w, h) / min(w, h), "frame"


def _order(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])


# ── 바탕 색감 ────────────────────────────────────────────

def colorfulness(bgr: np.ndarray, quad: np.ndarray | None, text_boxes: list[Quad], faces) -> float | None:
    stats = background_stats(bgr, quad, text_boxes, faces)
    return stats[0] if stats else None


def background_stats(bgr: np.ndarray, quad: np.ndarray | None, text_boxes: list[Quad],
                     faces) -> tuple[float, float, float] | None:
    """(밝기 보정 colorfulness, 평균 밝기, 하얗게 날아간 픽셀 비율). 카드 바탕에서만 잰다.

    colorfulness는 Hasler–Süsstrunk 값을 평균 밝기로 나눠 200 기준으로 맞춘다 (어두운 사진도 같은 척도).

    영역: 글자 박스 전체의 볼록 껍질 (글자는 항상 카드 위에 있으므로 책상·배경이 섞이지 않는다)
    제외: 글자 박스, 증명사진(얼굴 + 여백), 채도 높은 픽셀(직인 등 — 실물 바탕 무늬는 옅다)
    """
    h, w = bgr.shape[:2]
    pts = np.array([p for b in text_boxes for p in b], np.float32)
    if len(pts) < 3:
        return None
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(pts).astype(np.int32), 255)
    if quad is not None:
        card = np.zeros_like(mask)
        cv2.fillPoly(card, [quad.astype(np.int32)], 255)
        mask &= card
    for b in text_boxes:
        cv2.fillPoly(mask, [np.array(b, np.int32)], 0)
    for f in faces:
        fw = f.x1 - f.x0
        mask[max(0, int(f.y0 - 0.9 * f.h)):int(f.y1 + 1.3 * f.h), max(0, int(f.x0 - 0.8 * fw)):int(f.x1 + 0.8 * fw)] = 0
    sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 1]
    mask[sat > SATURATION_LIMIT] = 0
    px = bgr[mask > 0].astype(np.float32)
    if len(px) < 1000:
        return None
    b, g, r = px[:, 0], px[:, 1], px[:, 2]
    rg, yb = r - g, 0.5 * (r + g) - b
    raw = float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))
    brightness = float(px.mean())
    clipped = float((px.min(axis=1) >= 250).mean())
    return raw * 200.0 / max(brightness, 40.0), brightness, clipped
