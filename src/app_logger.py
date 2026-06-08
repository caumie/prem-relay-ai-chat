
from logging.config import dictConfig
from pathlib import Path
from typing import Protocol


class AppConfigLike(Protocol):
    @property
    def log_dir(self) -> Path: ...

    @property
    def log_level(self) -> str: ...


def configure_logging(config: AppConfigLike) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
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
                    "format": "%(asctime)s | %(levelname)-8s | %(pathname)s:%(lineno)d, %(funcName)s | %(message)s"
                },
                "access": {"format": "%(asctime)s | %(message)s"},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": config.log_level,
                },
                "log": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "level": config.log_level,
                    "filename": str(config.log_dir / "app.log"),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
                "error_log": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "level": "ERROR",
                    "filename": str(config.log_dir / "error.log"),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
                "access_log": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "access",
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
