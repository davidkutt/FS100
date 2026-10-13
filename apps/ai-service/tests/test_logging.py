import json
import logging

from ai_service.core.logging import JsonFormatter, configure_logging, request_id_var


def make_record(**extra: object) -> logging.LogRecord:
    configure_logging("info")  # installs the record factory that attaches the request id
    record = logging.getLogger("test").makeRecord(
        "test", logging.WARNING, __file__, 1, "hello %s", ("world",), None, extra=extra
    )
    return record


def test_formats_records_as_one_json_object() -> None:
    entry = json.loads(JsonFormatter().format(make_record(doc_id="d-1")))

    assert entry["level"] == "warning"
    assert entry["logger"] == "test"
    assert entry["msg"] == "hello world"
    assert entry["doc_id"] == "d-1"
    assert "request_id" not in entry
    assert entry["time"].endswith("+00:00")


def test_includes_the_current_request_id() -> None:
    token = request_id_var.set("req-42")
    try:
        record = logging.getLogger("test").makeRecord(
            "test", logging.INFO, __file__, 1, "inside a request", (), None
        )
    finally:
        request_id_var.reset(token)

    configure_logging("info")
    assert json.loads(JsonFormatter().format(record))["request_id"] == "req-42"


def test_reconfiguring_does_not_stack_handlers() -> None:
    configure_logging("info")
    configure_logging("debug")

    json_handlers = [h for h in logging.getLogger().handlers if type(h).__name__ == "_JsonHandler"]
    assert len(json_handlers) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_drops_uvicorn_colour_duplicates() -> None:
    entry = json.loads(JsonFormatter().format(make_record(color_message="\x1b[36mhello\x1b[0m")))

    assert "color_message" not in entry
