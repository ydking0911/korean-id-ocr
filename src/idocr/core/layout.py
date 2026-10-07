"""OCR 줄의 위치 계산 헬퍼."""

from dataclasses import dataclass

from idocr.core.result import Quad
from idocr.ocr.engine import OcrChar, OcrLine


@dataclass(frozen=True)
class Line:
    text: str
    score: float
    box: Quad
    chars: tuple[OcrChar, ...]

    @property
    def x0(self) -> float:
        return min(p[0] for p in self.box)

    @property
    def x1(self) -> float:
        return max(p[0] for p in self.box)

    @property
    def y0(self) -> float:
        return min(p[1] for p in self.box)

    @property
    def y1(self) -> float:
        return max(p[1] for p in self.box)

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


def to_lines(ocr_lines: list[OcrLine]) -> list[Line]:
    lines = [Line(l.text, l.score, l.box, l.chars) for l in ocr_lines if l.text.strip()]
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
    """줄 안 일부 글자의 박스. 세로는 줄 높이를 그대로 쓴다."""
    if not chars:
        return line.box
    xs = [p[0] for c in chars for p in c.box]
    return rect(min(xs), line.y0, max(xs), line.y1)


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
