"""주민등록증 앞면 추출.

레이아웃 (위→아래): 제목 '주민등록증' / 성명(한자) / 주민번호 / 주소(여러 줄) / 발급일 / 발급기관
주민번호 줄을 기준점으로 삼고, 나머지는 그 위·아래 상대 위치로 찾는다. 사진·직인은 주민번호 줄보다 오른쪽에 있다.
"""

from datetime import date

from idocr.core import text as T
from idocr.core.extract.common import Recognizer, find_rrn, read_address, read_issuer, read_name
from idocr.core.layout import Line
from idocr.core.result import DocumentType, Extraction, FieldValue

FIELDS = ("name", "name_hanja", "rrn", "address", "address_lines", "issue_date", "issuer")

# 주민등록증 최초 발급일
EARLIEST_ISSUE = date(1968, 11, 21)


def extract(lines: list[Line], title: Line | None, recognize: Recognizer | None = None,
            today: date | None = None) -> Extraction:
    today = today or date.today()
    fields: dict[str, FieldValue | None] = dict.fromkeys(FIELDS)
    warnings: list[str] = []
    derived: dict = {}

    rrn_line, rrn, fields["rrn"] = find_rrn(lines, warnings, today)
    if rrn is not None and fields["rrn"].valid:
        derived = T.rrn_derived(rrn)
    if rrn_line is None:
        return Extraction(DocumentType.RESIDENT_CARD, fields, warnings, derived)

    above = [l for l in lines
             if l.is_above(rrn_line) and l.x0 < rrn_line.x1 and l is not title
             and (title is None or l.is_below(title)) and T.HANGUL.search(l.text)]
    if above:
        fields["name"], fields["name_hanja"] = read_name(max(above, key=lambda l: l.y1), recognize)

    date_line = _find_issue_date(lines, rrn_line, fields, rrn, today)

    body = [l for l in lines
            if l.is_below(rrn_line) and l.x0 < rrn_line.x1 and l is not date_line
            and (date_line is None or l.is_above(date_line))]
    fields["address"], fields["address_lines"] = read_address(body)

    if date_line is not None:
        fields["issuer"] = read_issuer(lines, date_line, warnings)
    return Extraction(DocumentType.RESIDENT_CARD, fields, warnings, derived)


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
