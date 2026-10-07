"""주소 사전 교정.

1. 띄어쓰기 복원 (결정적 규칙): '세종길115' → '세종길 115', '102동806호' → '102동 806호', '74(주공' → '74 (주공'
2. 행정구역 교정: 시·도(닫힌 집합) → 그 시·도의 시·군·구. 한글을 자모로 풀어 편집거리를 재므로
   받침·모음 하나 차이('광역세'→'광역시', '륨'→'륭')를 1로 센다. 후보가 하나일 때만 바꾼다.
3. 선택 사전(도로명·건물명): IDOCR_ADDRESS_LEXICON 파일이 있으면 해당 토큰도 교정한다.

사전 원자료: vuski/admdongkor (CC BY 4.0). 생성: python -m tools.address.build_lexicon
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path

# ── 자모 편집거리 ──────────────────────────────────────────

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def jamo(s: str) -> list[str]:
    out = []
    for ch in s:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out += [_CHO[code // 588], _JUNG[(code % 588) // 28]]
            if code % 28:
                out.append(_JONG[code % 28])
        else:
            out.append(ch)
    return out


def jamo_distance(a: str, b: str) -> int:
    x, y = jamo(a), jamo(b)
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return prev[-1]


# ── 사전 ────────────────────────────────────────────────

@dataclass(frozen=True)
class Lexicon:
    sido: frozenset[str]
    sgg: dict[str, frozenset[str]]
    extra: frozenset[str] = field(default_factory=frozenset)  # 도로명·건물명 (선택)

    def sgg_of(self, sido: str) -> frozenset[str]:
        return self.sgg.get(sido, frozenset())


@lru_cache
def load_lexicon(extra_path: str | None = None) -> Lexicon:
    data = json.loads(resources.files("idocr.data").joinpath("admin_names.json").read_text(encoding="utf-8"))
    extra: frozenset[str] = frozenset()
    if extra_path and Path(extra_path).exists():
        words = Path(extra_path).read_text(encoding="utf-8").split()
        extra = frozenset(w for w in words if len(w) >= 2)
    return Lexicon(
        sido=frozenset(data["sido"]),
        sgg={k: frozenset(v) for k, v in data["sgg"].items()},
        extra=extra,
    )


def nearest(token: str, candidates, max_dist: int) -> str | None:
    """자모 편집거리 max_dist 이하에서 가장 가까운 후보가 하나뿐이면 그것."""
    best, best_d, tie = None, max_dist + 1, False
    for c in candidates:
        if abs(len(c) - len(token)) > 1:
            continue
        d = jamo_distance(token, c)
        if d < best_d:
            best, best_d, tie = c, d, False
        elif d == best_d:
            tie = True
    return best if best is not None and not tie else None


# ── 교정 ────────────────────────────────────────────────

_SPACING = [
    # 세종길115 → 세종길 115 (단 '테헤란로34번길'처럼 숫자 뒤에 번길이 오면 도로명의 일부)
    (re.compile(r"(?<=[로길])(?=\d+(?:-\d+)?(?:\s|$|\())"), " "),
    (re.compile(r"(?<=\d동)(?=\d+호)"), " "),                   # 102동806호 → 102동 806호
    (re.compile(r"(?<=\d차)(?=\d+층)"), " "),                   # 18차20층 → 18차 20층
    (re.compile(r"(?<=[\d가-힣])(?=\()"), " "),                 # 74(주공 → 74 (주공
    (re.compile(r"(?<=\))(?=[\d가-힣])"), " "),                 # )115동 → ) 115동
    (re.compile(r"(?<=[가-힣])(?=\d+차\))"), " "),              # 대륭테크노타운18차) → 대륭테크노타운 18차)
]


def fix_spacing(s: str) -> str:
    for pat, rep in _SPACING:
        s = pat.sub(rep, s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Correction:
    text: str
    changed: list[tuple[str, str]]  # (원래 토큰, 교정 토큰)
    valid: bool  # 시·도가 사전에 있음 (시·군·구는 있으면 교정만, 견본처럼 생략된 주소도 있음)


def correct_address(text: str, lex: Lexicon | None = None) -> Correction:
    lex = lex or load_lexicon()
    tokens = fix_spacing(text).split(" ")
    changed: list[tuple[str, str]] = []

    def fix(i: int, candidates, max_dist: int) -> bool:
        if tokens[i] in candidates:
            return True
        hit = nearest(tokens[i], candidates, max_dist)
        if hit:
            changed.append((tokens[i], hit))
            tokens[i] = hit
            return True
        return False

    sido_ok = bool(tokens) and fix(0, lex.sido, 2)
    # 시·군·구는 '시·군·구'로 끝나는 토큰만 교정한다 ('중앙로'가 '중앙구'로 바뀌지 않게)
    if sido_ok and len(tokens) > 1 and _looks_like_sgg(tokens[1]):
        sggs = lex.sgg_of(tokens[0])
        if fix(1, sggs, 1) and len(tokens) > 2 and tokens[1].endswith("시") and _looks_like_sgg(tokens[2]):
            fix(2, sggs, 1)  # 일반구가 있는 시: '성남시 분당구'


    if lex.extra:
        for i, t in enumerate(tokens):
            stem = re.sub(r"[()\d]+", "", t)
            if len(stem) >= 2 and stem not in lex.extra and T_HANGUL.search(stem):
                hit = nearest(stem, lex.extra, 1)
                if hit:
                    changed.append((t, t.replace(stem, hit)))
                    tokens[i] = t.replace(stem, hit)

    return Correction(" ".join(tokens), changed, sido_ok)


T_HANGUL = re.compile(r"[가-힣]")


def _looks_like_sgg(token: str) -> bool:
    """끝 글자가 시·군·구이거나 그와 자모 하나 차이('송파규')."""
    return len(token) >= 2 and any(jamo_distance(token[-1], s) <= 1 for s in ("시", "군", "구"))
