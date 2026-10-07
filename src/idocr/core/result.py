"""구조화 결과 타입. 응답 형식은 docs/05-output-schema.md."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

Quad = list[list[float]]  # 4점 [[x, y], ...]


class Status(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class DocumentType(str, Enum):
    RESIDENT_CARD = "RESIDENT_CARD"
    DRIVER_LICENSE = "DRIVER_LICENSE"
    UNKNOWN = "UNKNOWN"


class FailReason(str, Enum):
    IMAGE_DECODE_ERROR = "IMAGE_DECODE_ERROR"
    NO_TEXT = "NO_TEXT"
    UNSUPPORTED_DOCUMENT = "UNSUPPORTED_DOCUMENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INTERNAL = "INTERNAL"


@dataclass
class FieldValue:
    """추출된 필드 하나. value는 정규화된 값 (문자열, 리스트, dict 등)."""

    value: Any
    confidence: float
    boxes: list[Quad] = field(default_factory=list)
    valid: bool = True
    verified: bool = False  # 값 자체의 검증 장치로 확인됨 (주민번호 검증번호 일치) → 낮은 임계값 적용


@dataclass
class Extraction:
    document_type: DocumentType
    fields: dict[str, FieldValue | None]
    warnings: list[str] = field(default_factory=list)
    derived: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdDocumentResult:
    status: Status
    document_type: DocumentType
    fields: dict[str, Any]
    derived: dict[str, Any]
    field_meta: dict[str, dict[str, Any]]
    warnings: list[str]
    fail_reason: FailReason | None
    preprocess: dict[str, Any]
    document_checks: dict[str, Any] | None = None  # 위조 의심 신호 (판정과 무관한 참고값)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "document_type": self.document_type.value,
            "document_side": "FRONT" if self.document_type != DocumentType.UNKNOWN else "UNKNOWN",
            "fields": self.fields,
            "derived": self.derived,
            "field_meta": self.field_meta,
            "warnings": self.warnings,
            "fail_reason": self.fail_reason.value if self.fail_reason else None,
            "preprocess": self.preprocess,
            "document_checks": self.document_checks,
        }
