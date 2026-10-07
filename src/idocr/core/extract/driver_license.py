"""운전면허증 앞면 추출.

레이아웃 (위→아래, 오른쪽 본문 열): 면허종류(좌상단) / 제목 / 면허번호 / 성명 / 주민번호 / 주소(여러 줄) /
적성검사(갱신)기간 시작 / '기 간 : ~ 종료' / 발급일 + 발급기관(한 줄). 큰 사진은 왼쪽, 작은 사진과 보안코드는 오른쪽.
"""

from datetime import date

from idocr.core import text as T
from idocr.core.extract.common import Recognizer, find_rrn, read_address, read_issuer, read_name
from idocr.core.layout import Line, rows, union_box
from idocr.core.result import DocumentType, Extraction, FieldValue

FIELDS = ("license_number", "license_region", "license_types", "name", "rrn", "address", "address_lines",
          "aptitude_period", "issue_date", "conditions", "serial_code", "issuer", "name_en", "birth_date_en")


def extract(lines: list[Line], title: Line | None, recognize: Recognizer | None = None,
            today: date | None = None) -> Extraction:
    today = today or date.today()
    fields: dict[str, FieldValue | None] = dict.fromkeys(FIELDS)
    warnings: list[str] = []
    derived: dict = {}

    rrn_line, rrn, fields["rrn"] = find_rrn(lines, warnings, today)
    if rrn is not None and fields["rrn"].valid:
        derived.update(T.rrn_derived(rrn))
    lic_line = _find_license_number(lines, fields, warnings, derived)
    _find_license_types(lines, lic_line or rrn_line, fields)

    if rrn_line is None:
        return Extraction(DocumentType.DRIVER_LICENSE, fields, warnings, derived)

    # 본문 열: 주민번호 줄과 왼쪽 끝이 비슷한 줄들 (왼쪽 큰 사진·오른쪽 작은 사진 영역 제외)
    def in_column(l: Line) -> bool:
        return rrn_line.x0 - rrn_line.h <= l.x0 < rrn_line.x1

    above = [l for l in lines if l.is_above(rrn_line) and in_column(l) and T.HANGUL.search(l.text)
             and (lic_line is None or l.is_below(lic_line)) and l is not title]
    if above:
        fields["name"], _ = read_name(max(above, key=lambda l: l.y1), recognize)

    period_lines, label = _find_aptitude_period(lines, rrn_line, in_column, fields, derived, today)
    date_line = _find_issue_date(lines, rrn_line, period_lines, fields, rrn, today)

    # 주소는 적성검사 라벨·날짜 줄 전까지. 라벨을 못 읽어도(흐린 사진) 첫 날짜 줄에서 끊는다
    first_dated = next((l for l in sorted(lines, key=lambda l: l.cy)
                        if l.is_below(rrn_line) and in_column(l) and T.find_dates(l.text)), None)
    stops = [l for l in (label, first_dated, date_line) if l is not None]
    stop = min(stops, key=lambda l: l.cy) if stops else None
    body = [l for l in lines if l.is_below(rrn_line) and in_column(l) and (stop is None or l.is_above(stop))]
    fields["address"], fields["address_lines"] = read_address(body, warnings)

    if date_line is not None:
        issuer = read_issuer(lines, date_line, warnings)
        if issuer is not None:
            snapped, changed = T.snap_police_issuer(issuer.value)
            if changed:
                issuer.value = snapped
                if "REPAIRED:issuer" not in warnings:
                    warnings.append("REPAIRED:issuer")
            issuer.valid = issuer.value in T.POLICE_ISSUERS
        fields["issuer"] = issuer

    _find_serial_code(lines, rrn_line, fields)
    return Extraction(DocumentType.DRIVER_LICENSE, fields, warnings, derived)


def _find_license_number(lines, fields, warnings, derived):
    found = [(l, n) for l in lines for n in T.find_license_numbers(l.text)]
    if not found:
        return None
    line, no = found[0]
    distinct = {n.formatted() for _, n in found}
    if len(distinct) > 1:
        warnings.append("AMBIGUOUS:license_number")
    valid = T.license_number_is_valid(no) and len(distinct) == 1
    fields["license_number"] = FieldValue(no.formatted(), line.score, [line.box], valid)
    if no.region_name_printed:
        fields["license_region"] = FieldValue(no.region_name_printed, line.score, [line.box], True)
    if no.region in T.LICENSE_REGIONS:
        derived["license_region_name"] = T.LICENSE_REGIONS[no.region]
    return line


def _find_license_types(lines, anchor, fields):
    # 면허종류는 카드 위쪽(면허번호 줄보다 위)에 있다
    region = [l for l in lines if anchor is None or l.is_above(anchor)]
    hits = [(l, k) for l in region for k in T.find_license_types(l.text)]
    if not hits:
        return
    kinds = list(dict.fromkeys(k for _, k in hits))
    used = list(dict.fromkeys(id(l) for l, _ in hits))
    used_lines = [l for l in region if id(l) in used]
    fields["license_types"] = FieldValue(
        kinds, min(l.score for l in used_lines), [union_box([l.box for l in used_lines])],
        all(T.license_type_is_valid(k) for k in kinds))


def _find_aptitude_period(lines, rrn_line, in_column, fields, derived, today):
    """적성검사(갱신)기간: 라벨 줄과 그다음 줄에서 날짜 두 개 (시작, 종료)."""
    below = [l for l in lines if l.is_below(rrn_line)]
    label = next((l for l in sorted(below, key=lambda l: l.cy) if T.aptitude_kind(l.text) and in_column(l)), None)
    if label is None:
        return [], None

    # 라벨 줄부터 두 줄 안의 날짜를 줄 순서·왼쪽부터 (발급일+발급기관 줄은 제외)
    window = [l for l in below if label.cy - 0.5 * label.h <= l.cy <= label.cy + 2.0 * label.h
              and not _is_issue_line(l)]
    dated = [(l, d) for row in rows(window) for l in row for d in T.find_dates(l.text)][:2]
    if not dated:
        return [], label
    used = list(dict.fromkeys(id(l) for l, _ in dated))
    used_lines = [l for l in window if id(l) in used]
    start = dated[0][1]
    end = dated[1][1] if len(dated) > 1 else None
    value = {"start": start.iso or start.raw, "end": (end.iso or end.raw) if end else None,
             "kind": T.aptitude_kind(label.text)}
    valid = (end is not None and start.value is not None and end.value is not None
             and start.value <= end.value and (end.value - start.value).days <= 400)
    fields["aptitude_period"] = FieldValue(
        value, min(l.score for l in used_lines + [label]), [union_box([l.box for l in used_lines])], valid)
    if valid:
        derived["is_expired"] = end.value < today
    return used_lines, label


def _is_issue_line(line: Line) -> bool:
    return bool(T.find_dates(line.text)) and len(T.HANGUL.findall(T.text_after_numbers(line.text))) >= 3


def _find_issue_date(lines, rrn_line, period_lines, fields, rrn, today):
    skip = {id(l) for l in period_lines}
    cands = [(l, d) for l in lines if l.is_below(rrn_line) and id(l) not in skip for d in T.find_dates(l.text)]
    if not cands:
        return None
    line, found = max(cands, key=lambda c: c[0].cy)  # 맨 아래 날짜
    born = rrn.birth_date() if rrn else None
    earliest = date(born.year + 16, 1, 1) if born else date(1960, 1, 1)
    valid = T.issue_date_is_valid(found.value, earliest, today)
    fields["issue_date"] = FieldValue(found.iso or found.raw, line.score, [line.box], valid)
    return line


def _find_serial_code(lines, rrn_line, fields):
    # 오른쪽 작은 사진 아래. 본문 열보다 오른쪽에 있는 것을 우선
    cands = [(l, c) for l in lines if l.is_below(rrn_line) for c in [T.find_serial_code(l.text)] if c]
    if not cands:
        return
    line, code = max(cands, key=lambda c: c[0].x0)
    fields["serial_code"] = FieldValue(code, line.score, [line.box], True)
