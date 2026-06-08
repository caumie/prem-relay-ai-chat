
"""SQLite接続と現在スキーマの初期化を担当する。"""

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)
SCHEMA_SQL_PATH = Path(__file__).parent.parent / "schema.sql"


class Database:
    """SQLiteデータベースへの接続生成とスキーマ初期化を行う。"""

    def __init__(self, db_path: Path) -> None:
        """db_pathを受け取り、接続先SQLiteファイルとして保持する。"""
        self.db_path = db_path

    def initialize(self) -> None:
        """引数なし・戻り値なしで、DBファイル親ディレクトリ作成とスキーマ適用を行う。"""
        logger.debug("db.ensure path=%s", self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA_SQL_PATH.read_text(encoding="utf-8"))

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection]:
        """引数なしでSQLite接続を生成し、利用後に必ず閉じるcontext managerを返す。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("pragma foreign_keys = on")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
