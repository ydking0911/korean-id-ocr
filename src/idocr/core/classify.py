"""문서 종류 판별 (제목 키워드)."""

import re
from difflib import SequenceMatcher

from idocr.core.layout import Line
from idocr.core.result import DocumentType

RESIDENT_TITLE = "주민등록증"
LICENSE_TITLE = "자동차운전면허증"


def _hangul_only(text: str) -> str:
    return re.sub(r"[^가-힣]", "", text)


def title_score(text: str, title: str) -> float:
    """줄 안에서 제목과 가장 비슷한 구간의 유사도 (OCR 한두 글자 오류 허용)."""
    h = _hangul_only(text)
    if not h:
        return 0.0
    if title in h:
        return 1.0
    n = len(title)
    windows = [h[i:i + n] for i in range(max(1, len(h) - n + 1))]
    return max(SequenceMatcher(None, w, title).ratio() for w in windows)


def find_title(lines: list[Line], title: str, threshold: float = 0.7) -> Line | None:
    best = max(lines, key=lambda l: title_score(l.text, title), default=None)
    return best if best is not None and title_score(best.text, title) >= threshold else None


def classify(lines: list[Line]) -> tuple[DocumentType, Line | None]:
    resident = find_title(lines, RESIDENT_TITLE)
    if resident is not None:
        return DocumentType.RESIDENT_CARD, resident
    # 면허증은 '운전면허증' 일부만 읽혀도, 영문 병기만 읽혀도 인정
    license_ = find_title(lines, LICENSE_TITLE) or find_title(lines, "운전면허증", 0.8)
    if license_ is None:
        license_ = next((l for l in lines if re.search(r"driver'?s\s*licen", l.text, re.I)), None)
    if license_ is not None:
        return DocumentType.DRIVER_LICENSE, license_
    return DocumentType.UNKNOWN, None
