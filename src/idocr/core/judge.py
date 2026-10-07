"""필드 채택·status 판정과 응답 조립. 규칙은 docs/05-output-schema.md 6절."""

from dataclasses import dataclass
from typing import Any, Callable

from idocr.core.result import DocumentType, Extraction, FailReason, IdDocumentResult, Quad, Status


@dataclass(frozen=True)
class DocSpec:
    fields: tuple[str, ...]
    required: tuple[str, ...]
    core: tuple[str, ...]
    kinds: dict[str, str]  # 필드 → 임계값 종류 (numeric / text / address). 없으면 판정 제외


RESIDENT_SPEC = DocSpec(
    fields=("name", "name_hanja", "rrn", "address", "address_lines", "issue_date", "issuer"),
    required=("name", "rrn", "address", "issue_date", "issuer"),
    core=("name", "rrn"),
    kinds={"name": "text", "rrn": "numeric", "address": "address", "address_lines": "address",
           "issue_date": "numeric", "issuer": "text"},
)

LICENSE_SPEC = DocSpec(
    fields=("license_number", "license_region", "license_types", "name", "rrn", "address", "address_lines",
            "aptitude_period", "issue_date", "conditions", "serial_code", "issuer", "name_en", "birth_date_en"),
    required=("license_number", "license_types", "name", "rrn", "address", "aptitude_period", "issue_date", "issuer"),
    core=("name", "rrn", "license_number"),
    kinds={"license_number": "numeric", "license_types": "text", "name": "text", "rrn": "numeric",
           "address": "address", "address_lines": "address", "aptitude_period": "numeric",
           "issue_date": "numeric", "serial_code": "numeric", "issuer": "text"},
)

SPECS = {DocumentType.RESIDENT_CARD: RESIDENT_SPEC, DocumentType.DRIVER_LICENSE: LICENSE_SPEC}


@dataclass(frozen=True)
class Thresholds:
    numeric: float = 0.90
    text: float = 0.85
    address: float = 0.80

    def for_kind(self, kind: str | None) -> float | None:
        return getattr(self, kind) if kind else None


def accepted_fields(ex: Extraction, spec: DocSpec, th: Thresholds) -> set[str]:
    out = set()
    for key in spec.fields:
        fv = ex.fields.get(key)
        limit = th.for_kind(spec.kinds.get(key))
        if fv is not None and fv.valid and (limit is None or fv.confidence >= limit):
            out.add(key)
    return out


def decide(ex: Extraction, spec: DocSpec, th: Thresholds) -> tuple[Status, FailReason | None]:
    ok = accepted_fields(ex, spec, th)
    if not all(k in ok for k in spec.core):
        return Status.FAIL, FailReason.LOW_CONFIDENCE
    if all(k in ok for k in spec.required):
        return Status.OK, None
    return Status.PARTIAL, None


def rank(ex: Extraction | None, spec: DocSpec | None, th: Thresholds) -> tuple:
    """재시도 패스 중 더 좋은 결과 고르기: OK > PARTIAL > FAIL, 동률이면 채택 필드 수, 평균 신뢰도."""
    if ex is None or spec is None:
        return (0, 0, 0.0)
    status, _ = decide(ex, spec, th)
    ok = accepted_fields(ex, spec, th)
    confs = [ex.fields[k].confidence for k in spec.fields if ex.fields.get(k) is not None]
    order = {Status.OK: 3, Status.PARTIAL: 2, Status.FAIL: 1}[status]
    return (order, len(ok), sum(confs) / len(confs) if confs else 0.0)


def assemble(
    ex: Extraction,
    th: Thresholds,
    map_box: Callable[[Quad], Quad],
    preprocess: dict[str, Any],
    mask_rrn: bool = False,
) -> IdDocumentResult:
    spec = SPECS[ex.document_type]
    status, fail_reason = decide(ex, spec, th)
    ok = accepted_fields(ex, spec, th)

    fields: dict[str, Any] = {}
    meta: dict[str, dict[str, Any]] = {}
    for key in spec.fields:
        fv = ex.fields.get(key)
        if fv is None:
            fields[key] = None
            meta[key] = {"found": False, "confidence": None, "bbox": None, "valid": None, "accepted": False}
            continue
        value = fv.value
        if key == "rrn" and mask_rrn and isinstance(value, str):
            value = value[:8] + "******"
        fields[key] = value
        boxes = [map_box(b) for b in fv.boxes]
        meta[key] = {
            "found": True,
            "confidence": round(fv.confidence, 4),
            "bbox": boxes[0] if len(boxes) == 1 else boxes,
            "valid": fv.valid,
            "accepted": key in ok,
        }

    return IdDocumentResult(
        status=status,
        document_type=ex.document_type,
        fields=fields,
        derived=ex.derived,
        field_meta=meta,
        warnings=ex.warnings,
        fail_reason=fail_reason,
        preprocess=preprocess,
    )


def failure(reason: FailReason, preprocess: dict[str, Any],
            document_type: DocumentType = DocumentType.UNKNOWN, warnings: list[str] | None = None) -> IdDocumentResult:
    return IdDocumentResult(
        status=Status.FAIL,
        document_type=document_type,
        fields={},
        derived={},
        field_meta={},
        warnings=warnings or [],
        fail_reason=reason,
        preprocess=preprocess,
    )
