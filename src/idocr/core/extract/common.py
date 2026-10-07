"""주민등록증·운전면허증 공통 추출 단계."""

from datetime import date
from typing import Callable

from idocr.config import get_settings
from idocr.core import text as T
from idocr.core.address import correct_address, fix_spacing, load_lexicon
from idocr.core.layout import Line, chars_box, leading_chars, merge_row, rows, trailing_chars_after, union_box
from idocr.core.result import FieldValue, Quad

Recognizer = Callable[[Quad], tuple[str, float]]


def find_rrn(lines: list[Line], warnings: list[str], today: date) -> tuple[Line | None, T.Rrn | None, FieldValue | None]:
    found = [(l, r) for l in lines for r in T.find_rrns(l.text)]
    if not found:
        # 앞·뒷자리가 두 박스로 쪼개진 경우 (하이픈이 흐려 검출이 끊김): 같은 줄을 합쳐 다시 찾는다
        found = [(m, r) for row in rows(lines) if len(row) > 1 for m in [merge_row(row)] for r in T.find_rrns(m.text)]
    if not found:
        return None, None, None
    line, rrn = found[0]
    distinct = {r.formatted() for _, r in found}
    if len(distinct) > 1:
        warnings.append("AMBIGUOUS:rrn")
    if rrn.masked:
        warnings.append("MASKED:rrn")
    checksum = T.rrn_checksum_ok(rrn)
    if checksum is False:
        warnings.append("CHECKSUM_MISMATCH:rrn")
    valid = T.rrn_is_valid(rrn, today) and len(distinct) == 1
    return line, rrn, FieldValue(rrn.formatted(), _rrn_confidence(line, rrn), [line.box], valid,
                                 verified=bool(checksum))


def _rrn_confidence(line: Line, rrn: T.Rrn) -> float:
    """줄 평균이 아니라 주민번호 숫자 중 가장 낮은 글자 신뢰도. 숫자 하나만 애매한 경우를 놓치지 않는다.
    글자 박스를 못 맞추면 줄 신뢰도."""
    digits = rrn.front + rrn.gender_digit + (rrn.back_rest or "")
    chars = [c for c in line.chars if T.numeric_view(c.text).strip().isdigit()]
    seq = "".join(T.numeric_view(c.text).strip() for c in chars)
    i = seq.find(digits)
    if i < 0 or len(seq) != len(chars):
        return line.score
    # 숫자 글자만 본다: 가림 문자('******')는 신뢰도가 낮아도 판정과 무관
    return min(c.score for c in chars[i:i + len(digits)])


def read_name(line: Line, recognize: Recognizer | None) -> tuple[FieldValue | None, FieldValue | None]:
    """이름 줄 → (이름, 한자 이름). 한자·괄호가 붙어 있으면 한글 부분만 잘라 재인식한다."""
    name = T.leading_hangul(line.text)
    conf, box = line.score, line.box

    # 한자 등이 붙어 있으면 그 문맥 때문에 한글까지 틀리기 쉽다
    contaminated = line.text.replace(" ", "") != name
    lead = leading_chars(line, lambda c: bool(T.HANGUL.fullmatch(c)))
    if contaminated and recognize is not None and len(lead) >= 2:
        crop = chars_box(line, lead)
        pad = 0.25 * line.h
        crop = [[crop[0][0] - pad, crop[0][1]], [crop[1][0] + pad, crop[1][1]],
                [crop[2][0] + pad, crop[2][1]], [crop[3][0] - pad, crop[3][1]]]
        re_text, re_score = recognize(crop)
        re_name = T.leading_hangul(re_text)
        if T.name_is_valid(re_name):
            name, conf, box = re_name, re_score, crop
    elif lead:
        box = chars_box(line, lead)

    name_fv = FieldValue(name, conf, [box], T.name_is_valid(name)) if name else None
    hanja = T.hanja_in_parens(line.text)
    hanja_fv = FieldValue(hanja, line.score, [line.box], True) if hanja else None
    return name_fv, hanja_fv


def read_address(body: list[Line], warnings: list[str] | None = None) -> tuple[FieldValue | None, FieldValue | None]:
    """주소 영역 줄들 → (주소, 줄 목록). 한 줄이 여러 박스로 쪼개져도 줄 단위로 이어 붙인다.
    띄어쓰기 복원과 행정구역 사전 교정을 거친다 (core/address.py)."""
    # 번지만 있는 줄('154')처럼 한글이 없어도 숫자가 있으면 주소 줄이다
    body = [l for l in body if (T.HANGUL.search(l.text) or any(c.isdigit() for c in l.text))
            and len(l.text.strip()) >= 2]
    if not body:
        return None, None
    grouped = rows(body)
    # 발급일을 못 찾았을 때 대비: 발급기관처럼 끝나는 줄부터는 주소가 아니다
    for i, row in enumerate(grouped):
        if i > 0 and T.issuer_is_valid(T.repair_issuer(" ".join(l.text for l in row))[0]):
            grouped = grouped[:i]
            break
    body = [l for row in grouped for l in row]
    texts = [" ".join(T.collapse_spaces(l.text) for l in row) for row in grouped]
    texts[0] = T.space_after_sido(texts[0])
    texts = [fix_spacing(t) for t in texts]

    corr = correct_address(" ".join(texts), load_lexicon(get_settings().address_lexicon))
    for old, new in corr.changed:  # 교정한 토큰을 줄 목록에도 반영
        for i, t in enumerate(texts):
            toks = t.split(" ")
            if old in toks:
                toks[toks.index(old)] = new
                texts[i] = " ".join(toks)
                break
    if corr.changed and warnings is not None:
        warnings.append("REPAIRED:address")

    conf = min(l.score for l in body)
    boxes = [union_box([l.box for l in row]) for row in grouped]
    return (FieldValue(corr.text, conf, boxes, corr.valid),
            FieldValue(texts, conf, boxes, corr.valid))


def _has_issuer_prefix(row: list[Line]) -> bool:
    texts = [l.text for l in row if T.HANGUL.search(l.text)]
    return any(T.issuer_is_valid(T.repair_issuer(" ".join(texts[:i]))[0]) for i in range(1, len(texts) + 1))


def read_issuer(lines: list[Line], date_line: Line, warnings: list[str]) -> FieldValue | None:
    """발급일 줄 뒤(같은 박스 → 같은 줄 오른쪽 → 아래 줄 순)에서 발급기관을 찾는다."""
    rest = T.text_after_numbers(date_line.text)
    if len(T.HANGUL.findall(rest)) >= 3:
        box = chars_box(date_line, trailing_chars_after(date_line, lambda c: not T.HANGUL.search(c)))
        parts = [(rest, date_line.score, box)]
    else:
        right = [l for l in lines if l.same_row(date_line) and l.x0 > date_line.x1]
        below = rows([l for l in lines if l.is_below(date_line)])
        candidates = [right] + below if right else below
        hangul = [r for r in candidates if len(T.HANGUL.findall("".join(l.text for l in r))) >= 3]
        # 발급기관으로 끝나는 줄 우선 (같은 줄 오른쪽의 직인 노이즈 '영록특별시'보다 아래 '행복특별시 행복구청장')
        row = next((r for r in hangul if _has_issuer_prefix(r)), hangul[0] if hangul else None)
        if row is None:
            return None
        parts = [(l.text, l.score, l.box) for l in row]
    # 앞에 붙은 숫자만 있는 박스 제외 (신형 주민등록증 좌하단 고스트 이미지의 생년월일 '981032' 등)
    while len(parts) > 1 and not T.HANGUL.search(parts[0][0]):
        parts = parts[1:]

    # 왼쪽부터 이어 붙이다 발급기관 접미사가 완성되면 멈춘다 (오른쪽 직인·배경 노이즈 박스 배제)
    used = []
    for part in parts:
        used.append(part)
        if T.issuer_is_valid(T.repair_issuer(" ".join(t for t, _, _ in used))[0]):
            break
    issuer, repaired = T.repair_issuer(" ".join(t for t, _, _ in used))
    if repaired:
        warnings.append("REPAIRED:issuer")
    conf = min(sc for _, sc, _ in used)
    return FieldValue(issuer, conf, [union_box([b for _, _, b in used])], T.issuer_is_valid(issuer))
