
import logging
from contextvars import ContextVar, Token
from logging.config import dictConfig
from pathlib import Path
from typing import Protocol

_request_id: ContextVar[str] = ContextVar("request_id", default="")


class AppConfigLike(Protocol):
    @property
    def log_dir(self) -> Path: ...

    @property
    def log_level(self) -> str: ...


def current_request_id() -> str:
    """現在の request_id を返す。"""
    return _request_id.get()


def set_request_id(request_id: str) -> Token[str]:
    """request_id を現在の実行コンテキストへ設定する。"""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    """request_id を元の実行コンテキストへ戻す。"""
    _request_id.reset(token)


class RequestIdFilter(logging.Filter):
    """ログレコードへ request_id を注入する。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


def configure_logging(config: AppConfigLike) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "loggers": {
                "python_multipart": {"level": "WARNING", "propagate": False},
                "uvicorn": {"level": "WARNING", "propagate": False},
                "uvicorn.error": {"level": "WARNING", "propagate": False},
                "uvicorn.access": {
                    "handlers": ["access_log"],
                    "level": "INFO",
                    "propagate": False,
                },
                "src": {"level": config.log_level, "propagate": True},
            },
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)-8s | request_id=%(request_id)s | %(pathname)s:%(lineno)d, %(funcName)s | %(message)s"
                },
                "access": {"format": "%(asctime)s | %(message)s"},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "level": config.log_level,
                },
                "log": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "level": config.log_level,
                    "filename": str(config.log_dir / "app.log"),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
                "error_log": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "level": "ERROR",
                    "filename": str(config.log_dir / "error.log"),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
                "access_log": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "access",
                    "filters": ["request_id"],
                    "level": "INFO",
                    "filename": str(config.log_dir / "access.log"),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "handlers": ["console", "log", "error_log"],
                "level": config.log_level,
            },
        }
    )
