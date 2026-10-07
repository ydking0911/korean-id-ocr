"""로그 개인정보 보호.

- 6자리 이상 연속 숫자(하이픈·공백으로 이어진 것 포함)는 로그에 쓰기 전에 마스킹한다.
- 예외는 메시지 없이 타입명만 기록한다 (예외 메시지에 OCR 결과가 섞일 수 있음).
"""

import logging
import re

# "900101-1234567", "900101 1234567", "11-19-123456-61" 등
_DIGIT_RUN = re.compile(r"\d(?:[\d\s\-.]*\d)?")
_MASK = "[REDACTED]"


def _digit_count(s: str) -> int:
    return sum(c.isdigit() for c in s)


def redact(text: str) -> str:
    return _DIGIT_RUN.sub(lambda m: _MASK if _digit_count(m.group()) >= 6 else m.group(), text)


def _redact_arg(value):
    return redact(value) if isinstance(value, str) else value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # args는 버리지 않고 각각 마스킹한다. uvicorn AccessFormatter처럼 args를 직접 쓰는 포맷터가 있다
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _redact_arg(v) for k, v in record.args.items()}
        # 트레이스백 원문은 버리고 타입명만 남긴다
        if record.exc_info and record.exc_info[0] is not None:
            record.msg = f"{record.msg} [{record.exc_info[0].__name__}]"
            record.exc_info = None
            record.exc_text = None
        return True


def safe_exc(e: BaseException) -> str:
    return type(e).__name__


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    _install_filter(root)

    # uvicorn과 RapidOCR는 자체 핸들러를 쓰고 root로 전파하지 않으므로 직접 붙인다
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "RapidOCR"):
        _install_filter(logging.getLogger(name))
    logging.getLogger("RapidOCR").setLevel(logging.ERROR)


def _install_filter(logger: logging.Logger) -> None:
    targets = [logger, *logger.handlers]
    for t in targets:
        if not any(isinstance(f, RedactingFilter) for f in t.filters):
            t.addFilter(RedactingFilter())
