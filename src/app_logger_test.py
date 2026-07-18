"""app_logger の request_id 注入契約を検証する。"""

import logging

from src.app_logger import RequestIdFilter, current_request_id, reset_request_id, set_request_id


def test_request_id_context_defaults_to_empty_string() -> None:
    # 観点: request_id が未設定でも空文字を返すこと。
    # 目的: 非HTTP経路のログ出力を壊さずに formatter へ流せる契約を固定する。
    assert current_request_id() == ""


def test_request_id_filter_injects_current_request_id() -> None:
    # 観点: request_id filter がログレコードへ現在の相関IDを注入すること。
    # 目的: HTTP middleware で設定した request_id を handler まで伝搬できるようにする。
    token = set_request_id("req-123")
    try:
        record = logging.LogRecord(
            name="src.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )

        assert RequestIdFilter().filter(record) is True
        assert getattr(record, "request_id") == "req-123"
    finally:
        reset_request_id(token)
