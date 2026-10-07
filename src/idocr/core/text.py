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
# 뒷자리 2~7번째는 전부·일부 가려져 있을 수 있다 ('2******', '20200XX', 스티커로 가려 누락)
_MASKCH = "*xX●•"
# 하이픈 있음: 전체 / 일부 가림 / 스티커로 가려 뒷자리 누락('800101-2')
_RRN_HY = re.compile(rf"(?<!\d)(\d{{6}})\s*-\s*([0-9])([0-9{_MASKCH}]{{6}}|[{_MASKCH}]{{0,5}})(?![\d{_MASKCH}])")
# 하이픈 없음(또는 두 박스로 쪼개져 공백): 13자리 숫자, 또는 가림 문자가 섞인 경우만.
# 가림 문자 없는 7자리('2345678', 주소의 '9371203')를 가린 주민번호로 오인하지 않게 한다
_RRN_NOHY = re.compile(rf"(?<!\d)(\d{{6}})\s*([0-9])([0-9{_MASKCH}]{{6}})(?![\d{_MASKCH}])")
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
    found, spans = [], []
    for pat in (_RRN_HY, _RRN_NOHY):
        for m in pat.finditer(view):
            if any(a < m.end() and m.start() < b for a, b in spans):
                continue
            spans.append(m.span())
            rest = m.group(3)
            found.append((m.start(), Rrn(m.group(1), m.group(2), rest if len(rest) == 6 and rest.isdigit() else None)))
    return [r for _, r in sorted(found, key=lambda x: x[0])]


_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)


def rrn_checksum_ok(rrn: Rrn) -> bool | None:
    """마지막 자리 검증번호. 2020년 10월 이전 부여 번호에만 있다 (이후 부여·변경 번호는 임의 숫자).
    앞 12자리 중 한 자리를 잘못 읽으면 약 98%가 불일치로 드러난다. 가려져 있으면 None."""
    if rrn.back_rest is None:
        return None
    d = [int(c) for c in rrn.front + rrn.gender_digit + rrn.back_rest]
    check = (11 - sum(w * x for w, x in zip(_RRN_WEIGHTS, d)) % 11) % 10
    return check == d[12]


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

# 구분자는 '.', '-', '/' 외에 쉼표 오인식('2033,01.01.'), 둘째 구분자 누락('2019.1 28')도 허용
_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[.,\-/]\s*(\d{1,2})\s*[.,\-/\s]\s*(\d{1,2})(?:\s*[.,])?(?!\d)")


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
    """직인에 가려 끝 글자가 빠지거나 틀린 발급기관 보정. (값, 보정 여부)"""
    s = space_after_sido(collapse_spaces(issuer))
    s = re.sub(r"\s+(?=(?:장|청장|시장|군수)$)", "", s)  # '세종특별자치시 장' → '세종특별자치시장'
    if s.endswith(_ISSUER_SUFFIX):
        return s, False
    # 접미사 한 글자만 틀린 경우: '경찰청징' → '경찰청장'
    for suf in ("청장", "시장", "군수"):
        if len(s) >= 3 and s[-2] == suf[0] and HANGUL.fullmatch(s[-1]):
            return s[:-1] + suf[1], True
    for cut, fix in (("경찰", "경찰청장"), ("경찰청", "경찰청장"), ("구청", "구청장"), ("군청", "군수"),
                     ("시청", "시장"), ("구", "구청장"), ("군", "군수")):
        if s.endswith(cut):
            return s[: len(s) - len(cut)] + fix, True
    return s, False


# 면허 발급 경찰청 (2021년 이전 '○○지방경찰청장', 2016년 이전 경기는 남·북부 분리 전)
_POLICE_REGIONS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "경기남부", "경기북부",
                   "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주")
# 신형 명칭(2021~): '서울특별시경찰청장', '경기도남부경찰청장' 등 (실물 샘플에서 확인)
_POLICE_FULL = ("서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
                "세종특별자치시", "경기도남부", "경기도북부", "강원특별자치도", "강원도", "충청북도", "충청남도",
                "전북특별자치도", "전라북도", "전라남도", "경상북도", "경상남도", "제주특별자치도")
POLICE_ISSUERS = tuple(f"{r}{j}경찰청장" for r in _POLICE_REGIONS for j in ("", "지방")) + tuple(
    f"{r}경찰청장" for r in _POLICE_FULL)


def snap_police_issuer(issuer: str, min_ratio: float = 0.75) -> tuple[str, bool]:
    """면허증 발급기관은 닫힌 집합 → 가장 가까운 값으로 맞춘다. (값, 바뀌었는지)"""
    from difflib import SequenceMatcher

    s = re.sub(r"\s", "", issuer)
    if s in POLICE_ISSUERS:
        return s, False  # 띄어쓰기만 다른 건 보정으로 보지 않음
    best = max(POLICE_ISSUERS, key=lambda c: SequenceMatcher(None, s, c).ratio())
    if SequenceMatcher(None, s, best).ratio() >= min_ratio:
        return best, True
    return issuer, False


def issuer_is_valid(issuer: str) -> bool:
    return issuer.endswith(_ISSUER_SUFFIX) and len(issuer) >= 4


# ── 운전면허 ─────────────────────────────────────────────

# 면허번호 앞 2자리 지역코드 (docs/05-output-schema.md 3절)
LICENSE_REGIONS = {
    "11": "서울", "12": "부산", "13": "경기", "14": "강원", "15": "충북", "16": "충남", "17": "전북",
    "18": "전남", "19": "경북", "20": "경남", "21": "제주", "22": "대구", "23": "인천", "24": "광주",
    "25": "대전", "26": "울산", "28": "경기북부",
}
_REGION_CODE = {name: code for code, name in LICENSE_REGIONS.items()}

_MASK = r"[\dXx*●•]"
_LICENSE_NO = re.compile(rf"(?<!\d)(\d{{2}})\s*-\s*(\d{{2}})\s*-\s*({_MASK}{{6}})\s*-\s*({_MASK}{{2}})(?![\dXx])")
# 구형: '서울 19-123456-61' (지역명 + 10자리)
_LICENSE_NO_OLD = re.compile(r"(" + "|".join(sorted(_REGION_CODE, key=len, reverse=True)) + r")\s*"
                             r"(\d{2})\s*-\s*(\d{6})\s*-\s*(\d{2})(?!\d)")


@dataclass(frozen=True)
class LicenseNo:
    region: str  # 지역코드 2자리
    year: str
    serial: str
    check: str
    region_name_printed: str | None = None  # 구형 표기의 지역명

    @property
    def masked(self) -> bool:
        return not (self.serial + self.check).isdigit()

    def formatted(self) -> str:
        serial = re.sub(r"[^\d]", "X", self.serial)
        check = re.sub(r"[^\d]", "X", self.check)
        return f"{self.region}-{self.year}-{serial}-{check}"


def find_license_numbers(text: str) -> list[LicenseNo]:
    out = []
    for m in _LICENSE_NO_OLD.finditer(text):
        out.append(LicenseNo(_REGION_CODE[m.group(1)], m.group(2), m.group(3), m.group(4), m.group(1)))
    if not out:
        view = numeric_view(text)
        out = [LicenseNo(*m.groups()) for m in _LICENSE_NO.finditer(view)]
    return out


def license_number_is_valid(no: LicenseNo) -> bool:
    return no.region in LICENSE_REGIONS


LICENSE_TYPES = {"1종대형", "1종보통", "1종소형", "1종특수", "2종보통", "2종소형", "2종원동기"}


_KIND = re.compile(r"(?:(?<!\d)([12])\s*종?\s*)?([가-힣]{2,3})(?:\s*[(（]([^)）]*)[)）])?")
_KIND_NAMES = ("대형", "보통", "소형", "특수", "원동기")


def _kind_name(word: str) -> str | None:
    """'보통'·'보동'(한 글자 오인식) → '보통'. 면허종류가 아니면 None."""
    from idocr.core.address import jamo_distance

    w = re.sub(r"\s", "", word)
    if w in _KIND_NAMES:
        return w
    near = [k for k in _KIND_NAMES if len(k) == len(w) and jamo_distance(w, k) <= 1]
    return near[0] if len(near) == 1 else None
_SPECIAL = ("대형견인", "소형견인", "구난")


def find_license_types(text: str) -> list[str]:
    """'1종 보통' → ['1종보통']. 실물처럼 여러 줄·접두사 생략도 처리:
    '1종대형 1종보통' / '특수(대형견인,소형견인,구난)' → 1종특수(…) 각각 / '원동기' → 2종원동기.
    종 표기가 없으면 같은 줄 앞의 종을 따른다."""
    out: list[str] = []
    last = None
    for m in _KIND.finditer(text.replace("l", "1").replace("I", "1")):
        kind = _kind_name(m.group(2))
        if kind is None:
            continue
        grade = m.group(1) or {"특수": "1", "원동기": "2"}.get(kind) or last
        if grade is None:
            continue
        last = grade
        if kind == "특수":
            subs = [x for x in re.split(r"[,·.\s]+", m.group(3) or "") if x in _SPECIAL]
            out += [f"1종특수({x})" for x in subs] or ["1종특수"]
        else:
            out.append(f"{grade}종{kind}")
    return list(dict.fromkeys(out))


def license_type_is_valid(kind: str) -> bool:
    return kind.split("(")[0] in LICENSE_TYPES


_SERIAL = re.compile(r"[A-Z0-9]{6}")

# 경찰청 진위조회 안내에도 혼동 주의로 나오는 글자들. 실물 코드에 O·I도 쓰이므로 한쪽으로 바꾸지 않는다
LOOKALIKES = ({"O", "0", "Q"}, {"I", "1"})
_MAX_ALTERNATIVES = 16


def find_serial_code(text: str) -> str | None:
    """보안코드(암호일련번호): 영대문자·숫자 6자리. 숫자가 없는 코드도 있다(무작위 6자리의 약 14%).
    소문자가 섞이면 직인 노이즈('oioisu')로 보고 버린다."""
    s = re.sub(r"\s", "", text)
    return s if _SERIAL.fullmatch(s) else None


def serial_alternatives(code: str) -> list[str]:
    """비슷한 글자를 바꿔 만든 다른 후보 (원래 값 제외). 너무 많으면(>16) 빈 목록."""
    options = []
    for c in code:
        group = next((g for g in LOOKALIKES if c in g), None)
        options.append(sorted(group) if group else [c])
    total = 1
    for o in options:
        total *= len(o)
    if total - 1 > _MAX_ALTERNATIVES:
        return []
    out = [""]
    for o in options:
        out = [p + c for p in out for c in o]
    return [a for a in out if a != code]


def has_lookalike(code: str) -> bool:
    return any(c in g for c in code for g in LOOKALIKES)


def aptitude_kind(text: str) -> str | None:
    h = re.sub(r"[^가-힣]", "", text)
    if "적성" in h:
        return "APTITUDE"
    if "갱신" in h:
        return "RENEWAL"
    return None
