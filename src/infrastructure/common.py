
"""Repository実装で共有する日時処理を定義する。"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
