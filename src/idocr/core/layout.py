"""OCR 줄의 위치 계산 헬퍼."""

import math
import statistics
from dataclasses import dataclass

from idocr.core.result import Quad
from idocr.ocr.engine import OcrChar, OcrLine


@dataclass(frozen=True)
class Line:
    text: str
    score: float
    box: Quad  # 원래 좌표 (응답 bbox·영역 잘라내기용)
    chars: tuple[OcrChar, ...]
    geo: Quad | None = None  # 기울기를 되돌린 좌표 (위치 비교용). 없으면 box

    @property
    def _g(self) -> Quad:
        return self.geo or self.box

    @property
    def x0(self) -> float:
        return min(p[0] for p in self._g)

    @property
    def x1(self) -> float:
        return max(p[0] for p in self._g)

    @property
    def y0(self) -> float:
        return min(p[1] for p in self._g)

    @property
    def y1(self) -> float:
        return max(p[1] for p in self._g)

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    # 위치 비교는 중심 좌표로 한다. 기울어진 사진에서는 축 정렬 박스가 세로로 겹치기 때문
    def is_below(self, other: "Line") -> bool:
        return self.cy > other.cy + 0.5 * min(self.h, other.h)

    def is_above(self, other: "Line") -> bool:
        return other.is_below(self)

    def same_row(self, other: "Line") -> bool:
        return abs(self.cy - other.cy) <= 0.5 * min(self.h, other.h)


def text_angle(ocr_lines: list[OcrLine]) -> float:
    """긴 줄들의 기울기 중앙값(라디안). 박스 윗변(0→1번 점) 방향으로 잰다."""
    angles = []
    for l in ocr_lines:
        (ax, ay), (bx, by) = l.box[0], l.box[1]
        w = math.hypot(bx - ax, by - ay)
        h = math.hypot(l.box[3][0] - ax, l.box[3][1] - ay)
        if len(l.text.strip()) >= 3 and w > 2 * h:
            angles.append(math.atan2(by - ay, bx - ax))
    return statistics.median(angles) if angles else 0.0


def to_lines(ocr_lines: list[OcrLine]) -> list[Line]:
    ocr_lines = [l for l in ocr_lines if l.text.strip()]
    theta = text_angle(ocr_lines)
    if abs(theta) < math.radians(1):
        lines = [Line(l.text, l.score, l.box, l.chars) for l in ocr_lines]
    else:
        # 위치 비교는 기울기를 되돌린 좌표로 (기울어진 사진에서 줄이 섞이지 않게)
        c, s = math.cos(-theta), math.sin(-theta)
        unrotate = lambda q: [[x * c - y * s, x * s + y * c] for x, y in q]  # noqa: E731
        lines = [Line(l.text, l.score, l.box, l.chars, unrotate(l.box)) for l in ocr_lines]
    return sorted(lines, key=lambda l: (l.y0, l.x0))


def rows(lines: list[Line]) -> list[list[Line]]:
    """같은 줄에 있는 박스끼리 묶어 위→아래, 각 줄은 왼쪽→오른쪽 순으로."""
    out: list[list[Line]] = []
    for line in sorted(lines, key=lambda l: l.cy):
        if out and any(line.same_row(o) for o in out[-1]):
            out[-1].append(line)
        else:
            out.append([line])
    return [sorted(r, key=lambda l: l.x0) for r in out]


def rect(x0: float, y0: float, x1: float, y1: float) -> Quad:
    return [[round(x0, 1), round(y0, 1)], [round(x1, 1), round(y0, 1)],
            [round(x1, 1), round(y1, 1)], [round(x0, 1), round(y1, 1)]]


def union_box(boxes: list[Quad]) -> Quad:
    xs = [p[0] for b in boxes for p in b]
    ys = [p[1] for b in boxes for p in b]
    return rect(min(xs), min(ys), max(xs), max(ys))


def chars_box(line: Line, chars: list[OcrChar]) -> Quad:
    """줄 안 일부 글자의 박스 (원래 좌표). 세로는 줄 높이를 그대로 쓴다."""
    if not chars:
        return line.box
    xs = [p[0] for c in chars for p in c.box]
    ys = [p[1] for p in line.box]
    return rect(min(xs), min(ys), max(xs), max(ys))


def leading_chars(line: Line, pred) -> list[OcrChar]:
    out = []
    for c in line.chars:
        if not pred(c.text):
            break
        out.append(c)
    return out


def trailing_chars_after(line: Line, pred_stop) -> list[OcrChar]:
    """pred_stop을 만족하는 마지막 글자 이후의 글자들."""
    last = -1
    for i, c in enumerate(line.chars):
        if pred_stop(c.text):
            last = i
    return list(line.chars[last + 1:])
