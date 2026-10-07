"""주민등록증 앞면 추출.

레이아웃 (위→아래): 제목 '주민등록증' / 성명(한자) / 주민번호 / 주소(여러 줄) / 발급일 / 발급기관
주민번호 줄을 기준점으로 삼고, 나머지는 그 위·아래 상대 위치로 찾는다. 사진·직인은 주민번호 줄보다 오른쪽에 있다.
"""

from datetime import date
from typing import Callable

from idocr.core import text as T
from idocr.core.layout import Line, chars_box, leading_chars, rows, trailing_chars_after, union_box
from idocr.core.result import DocumentType, Extraction, FieldValue, Quad

Recognizer = Callable[[Quad], tuple[str, float]]

FIELDS = ("name", "name_hanja", "rrn", "address", "address_lines", "issue_date", "issuer")

# 주민등록증 최초 발급일
EARLIEST_ISSUE = date(1968, 11, 21)


def extract(lines: list[Line], title: Line | None, recognize: Recognizer | None = None,
            today: date | None = None) -> Extraction:
    today = today or date.today()
    fields: dict[str, FieldValue | None] = dict.fromkeys(FIELDS)
    warnings: list[str] = []
    derived: dict = {}

    rrn_line, rrn = _find_rrn(lines, fields, warnings, today)
    if rrn is not None and fields["rrn"].valid:
        derived = T.rrn_derived(rrn)

    if rrn_line is not None:
        _find_name(lines, title, rrn_line, fields, recognize)
        date_line = _find_issue_date(lines, rrn_line, fields, rrn, today)
        _find_address(lines, rrn_line, date_line, fields)
        if date_line is not None:
            _find_issuer(lines, date_line, fields, warnings)

    if rrn is not None and rrn.masked:
        warnings.append("MASKED:rrn")
    return Extraction(DocumentType.RESIDENT_CARD, fields, warnings, derived)


def _find_rrn(lines, fields, warnings, today):
    found = [(l, r) for l in lines for r in T.find_rrns(l.text)]
    if not found:
        return None, None
    line, rrn = found[0]
    distinct = {r.formatted() for _, r in found}
    valid = T.rrn_is_valid(rrn, today) and len(distinct) == 1
    if len(distinct) > 1:
        warnings.append("AMBIGUOUS:rrn")
    fields["rrn"] = FieldValue(rrn.formatted(), line.score, [line.box], valid)
    return line, rrn


def _find_name(lines, title, rrn_line, fields, recognize):
    above = [l for l in lines
             if l.is_above(rrn_line) and l.x0 < rrn_line.x1 and l is not title
             and (title is None or l.is_below(title)) and T.HANGUL.search(l.text)]
    if not above:
        return
    line = max(above, key=lambda l: l.y1)  # 주민번호 바로 위 줄
    name = T.leading_hangul(line.text)
    conf, box = line.score, line.box

    # 한자 등이 붙어 있으면 그 문맥 때문에 한글까지 틀리기 쉽다 → 한글 부분만 잘라 다시 인식
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

    if name:
        fields["name"] = FieldValue(name, conf, [box], T.name_is_valid(name))
    hanja = T.hanja_in_parens(line.text)
    if hanja:
        fields["name_hanja"] = FieldValue(hanja, line.score, [line.box], True)


def _find_issue_date(lines, rrn_line, fields, rrn, today):
    below = [(l, d) for l in lines if l.is_below(rrn_line) for d in T.find_dates(l.text)]
    if not below:
        return None
    line, found = below[0]
    valid = T.issue_date_is_valid(found.value, EARLIEST_ISSUE, today)
    born = rrn.birth_date() if rrn else None
    if valid and born and found.value < date(born.year + 16, 1, 1):
        valid = False  # 주민등록증은 만 17세 이후 발급
    fields["issue_date"] = FieldValue(found.iso or found.raw, line.score, [line.box], valid)
    return line


def _find_address(lines, rrn_line, date_line, fields):
    body = [l for l in lines
            if l.is_below(rrn_line) and l.x0 < rrn_line.x1
            and (date_line is None or l.is_above(date_line))
            and l is not date_line and T.HANGUL.search(l.text) and len(l.text.strip()) >= 2]
    if not body:
        return
    # 한 줄이 여러 박스로 쪼개져도 줄 단위로 다시 이어 붙인다
    grouped = rows(body)
    texts = [" ".join(T.collapse_spaces(l.text) for l in row) for row in grouped]
    texts[0] = T.space_after_sido(texts[0])
    address = " ".join(texts)
    conf = min(l.score for l in body)
    boxes = [union_box([l.box for l in row]) for row in grouped]
    fields["address"] = FieldValue(address, conf, boxes, T.address_is_valid(address))
    fields["address_lines"] = FieldValue(texts, conf, boxes, T.address_is_valid(address))


def _find_issuer(lines, date_line, fields, warnings):
    # 같은 박스에 날짜와 발급기관이 붙어 나오는 경우 (면허증과 같은 배치)
    rest = T.text_after_numbers(date_line.text)
    if len(T.HANGUL.findall(rest)) >= 3:
        box = chars_box(date_line, trailing_chars_after(date_line, lambda c: not T.HANGUL.search(c)))
        parts = [(rest, date_line.score, box)]
    else:
        right = [l for l in lines if l.same_row(date_line) and l.x0 > date_line.x1]
        below = rows([l for l in lines if l.is_below(date_line)])
        candidates = [right] + below if right else below
        row = next((r for r in candidates if len(T.HANGUL.findall("".join(l.text for l in r))) >= 3), None)
        if row is None:
            return
        parts = [(l.text, l.score, l.box) for l in row]

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
    fields["issuer"] = FieldValue(issuer, conf, [union_box([b for _, _, b in used])], T.issuer_is_valid(issuer))
