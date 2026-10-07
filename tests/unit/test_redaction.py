import logging

import pytest

from idocr.privacy.logging import RedactingFilter, redact


@pytest.mark.parametrize(
    "text",
    [
        "900101-1234567",
        "900101 - 1234567",
        "주민번호 9001011234567 끝",
        "11-19-123456-61",
        "2020.01.01",
        "123456",
    ],
)
def test_redacts_runs_of_six_or_more_digits(text):
    out = redact(text)
    assert sum(c.isdigit() for c in out) < 6


@pytest.mark.parametrize("text", ["workers=2 threads=3", "elapsed 412ms", "HTTP 503", "12345"])
def test_keeps_short_numbers(text):
    assert redact(text) == text


def test_filter_redacts_args_and_drops_traceback(caplog):
    logger = logging.getLogger("test.redaction")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.redaction"):
        try:
            raise ValueError("leaked 900101-1234567")
        except ValueError:
            logger.exception("ocr text: %s", "900101-1234567")

    record = caplog.records[-1]
    assert "1234567" not in caplog.text
    assert "[ValueError]" in record.getMessage()
    assert record.exc_info is None


def test_uvicorn_access_formatter_still_works():
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("172.17.0.1:5987", "POST", "/v1/ocr/raw?q=900101-1234567", "1.1", 200), None,
    )
    assert RedactingFilter().filter(record)
    out = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert "POST" in out and "200" in out
    assert "1234567" not in out
