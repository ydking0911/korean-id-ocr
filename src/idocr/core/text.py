"""필드 값 정규화·검증 (OCR과 무관한 순수 함수)."""

import re
from dataclasses import dataclass
from datetime import date

HANGUL = re.compile(r"[가-힣]")
HANJA = re.compile(r"[一-鿿㐀-䶿豈-﫿]")

# 숫자 자리에서 흔한 OCR 혼동. 숫자가 대부분인 토큰에만 적용한다
_DIGIT_LOOKALIKE = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1",
                                  "i": "1", "!": "1", "S": "5", "B": "8", "Z": "2", "z": "2"})
_DASHES = str.maketrans({"–": "-", "—": "-", "―": "-", "~": "-", "_": "-", "−": "-"})


def collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def fix_digits(token: str) -> str:
    digits = sum(c.isdigit() for c in token)
    letters = sum(c.isalnum() for c in token)
    if letters and digits / letters >= 0.6:
        return token.translate(_DIGIT_LOOKALIKE)
    return token


def numeric_view(text: str) -> str:
    """숫자 위주 토큰의 혼동 문자를 고치고 대시를 통일한 문자열 (숫자 패턴 매칭 전용).

    한글과 그 외 문자 사이를 띄워 토큰을 나눈다: '2014.11.21.서울' → '2014.11.21.' '서울'
    """
    spaced = re.sub(r"(?<=[가-힣])(?=[^가-힣\s])|(?<=[^가-힣\s])(?=[가-힣])", " ", text.translate(_DASHES))
    return " ".join(fix_digits(t) for t in spaced.split())


def text_after_numbers(text: str) -> str:
    """숫자 뒤에 이어지는 한글 시작 부분. '2014. 11. 21. 서울지방경찰' → '서울지방경찰'."""
    m = re.search(r"\d[\s.]*([가-힣].*)$", text)
    return collapse_spaces(m.group(1)) if m else ""


# ── 주민등록번호 ──────────────────────────────────────────

# 앞 6 + (구분자) + 뒤 7. 뒷자리 2~7번째는 가려져 있을 수 있다(*, X, ●, 누락)
_RRN = re.compile(r"(?<!\d)(\d{6})\s*-?\s*([0-9])([0-9]{6}|[*xX●•]{6}|[*xX●•]{0,6})(?!\d)")
_CENTURY = {"1": 1900, "2": 1900, "5": 1900, "6": 1900, "3": 2000, "4": 2000, "7": 2000, "8": 2000,
            "9": 1800, "0": 1800}


@dataclass(frozen=True)
class Rrn:
    front: str
    gender_digit: str
    back_rest: str | None  # 가려졌으면 None

    @property
    def masked(self) -> bool:
        return self.back_rest is None

    def formatted(self, mask: bool = False) -> str:
        rest = "******" if (mask or self.back_rest is None) else self.back_rest
        return f"{self.front}-{self.gender_digit}{rest}"

    def birth_date(self) -> date | None:
        century = _CENTURY[self.gender_digit]
        try:
            return date(century + int(self.front[:2]), int(self.front[2:4]), int(self.front[4:6]))
        except ValueError:
            return None


def find_rrns(text: str) -> list[Rrn]:
    view = numeric_view(text)
    found = []
    for m in _RRN.finditer(view):
        rest = m.group(3)
        found.append(Rrn(m.group(1), m.group(2), rest if len(rest) == 6 and rest.isdigit() else None))
    return found


def rrn_is_valid(rrn: Rrn, today: date | None = None) -> bool:
    today = today or date.today()
    if rrn.gender_digit in "90":  # 1800년대 출생: 사실상 OCR 오류
        return False
    born = rrn.birth_date()
    return born is not None and born <= today and today.year - born.year <= 120


def rrn_derived(rrn: Rrn) -> dict:
    born = rrn.birth_date()
    return {
        "birth_date": born.isoformat() if born else None,
        "sex": "M" if int(rrn.gender_digit) % 2 == 1 else "F",
        "is_foreign_resident": rrn.gender_digit in "5678",
    }


# ── 날짜 ─────────────────────────────────────────────────

_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?:\s*\.)?(?!\d)")


@dataclass(frozen=True)
class FoundDate:
    value: date | None  # 형식은 맞지만 존재하지 않는 날짜면 None
    raw: str

    @property
    def iso(self) -> str | None:
        return self.value.isoformat() if self.value else None


def find_dates(text: str) -> list[FoundDate]:
    view = numeric_view(text)
    out = []
    for m in _DATE.finditer(view):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            d = None
        out.append(FoundDate(d, m.group(0)))
    return out


def issue_date_is_valid(d: date | None, earliest: date, today: date | None = None) -> bool:
    today = today or date.today()
    return d is not None and earliest <= d <= today


# ── 이름·주소·발급기관 ─────────────────────────────────────

def leading_hangul(text: str) -> str:
    """앞쪽의 한글 연속 구간 (공백 무시). '홍길동(洪吉洞)' → '홍길동'."""
    m = re.match(r"\s*([가-힣](?:\s*[가-힣])*)", text)
    return re.sub(r"\s+", "", m.group(1)) if m else ""


def name_is_valid(name: str) -> bool:
    return bool(re.fullmatch(r"[가-힣]{2,5}", name))


def hanja_in_parens(text: str) -> str | None:
    m = re.search(r"[(（]\s*([^)）]+?)\s*[)）]", text)
    if m and HANJA.search(m.group(1)) and not HANGUL.search(m.group(1)):
        return re.sub(r"\s+", "", m.group(1))
    return None


_SIDO = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
         "충청북", "충북", "충청남", "충남", "전라북", "전북", "전라남", "전남",
         "경상북", "경북", "경상남", "경남", "제주")


_SIDO_FULL = ("서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
              "세종특별자치시", "경기도", "강원특별자치도", "강원도", "충청북도", "충청남도", "전북특별자치도",
              "전라북도", "전라남도", "경상북도", "경상남도", "제주특별자치도")


def space_after_sido(s: str) -> str:
    """'서울특별시금천구청장' → '서울특별시 금천구청장'."""
    for sido in _SIDO_FULL:
        if s.startswith(sido) and len(s) > len(sido) and s[len(sido)] != " ":
            return sido + " " + s[len(sido):]
    return s


def address_is_valid(address: str) -> bool:
    return address.startswith(_SIDO) and len(address) >= 8


_ISSUER_SUFFIX = ("청장", "시장", "군수", "읍장", "면장", "동장")


def repair_issuer(issuer: str) -> tuple[str, bool]:
    """직인에 가려 끝 글자가 빠진 발급기관 보정. (값, 보정 여부)"""
    s = space_after_sido(collapse_spaces(issuer))
    if s.endswith(_ISSUER_SUFFIX):
        return s, False
    for cut, fix in (("경찰", "경찰청장"), ("경찰청", "경찰청장"), ("구청", "구청장"), ("군청", "군수"),
                     ("시청", "시장"), ("구", "구청장"), ("군", "군수")):
        if s.endswith(cut):
            return s[: len(s) - len(cut)] + fix, True
    return s, False


def issuer_is_valid(issuer: str) -> bool:
    return issuer.endswith(_ISSUER_SUFFIX) and len(issuer) >= 4
