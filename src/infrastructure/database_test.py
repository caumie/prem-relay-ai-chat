"""DatabaseがSQLite接続とスキーマ初期化を担うことを検証する。"""

import sqlite3
from pathlib import Path

import pytest

from src.infrastructure import AuthRepository
from src.infrastructure.database import Database


def test_initialize_creates_parent_directory_and_applies_schema(tmp_path: Path) -> None:
    """db_pathを受け取り、親ディレクトリ作成後に現在スキーマを適用する。"""
    # 観点: 初期化
    # 目的: Database.initializeがDB利用前に必要なファイル配置とテーブルを用意する。
    db_path = tmp_path / "nested" / "chat.sqlite3"

    Database(db_path).initialize()

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }
    assert "active_users" in table_names
    assert "threads" in table_names


def test_initialize_applies_chat_schema_shape(tmp_path: Path) -> None:
    """db_pathを受け取り、チャット永続化に必要な主要テーブル定義を適用する。"""
    # 観点: スキーマ
    # 目的: Database.initializeが現在の認証・チャット・添付テーブル構造を作る責務を固定する。
    db_path = tmp_path / "chat.sqlite"
    Database(db_path).initialize()

    with sqlite3.connect(db_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }
        active_users_columns = {
            row[1]: {"type": row[2].lower(), "pk": row[5]}
            for row in conn.execute("pragma table_info(active_users)")
        }
        deleted_users_columns = {
            row[1]: {"type": row[2].lower(), "pk": row[5]}
            for row in conn.execute("pragma table_info(deleted_users)")
        }
        threads_columns = {
            row[1]: {"type": row[2].lower(), "pk": row[5]}
            for row in conn.execute("pragma table_info(threads)")
        }
        messages_columns = {
            row[1]: {"type": row[2].lower(), "pk": row[5]}
            for row in conn.execute("pragma table_info(messages)")
        }
        base_assistants_columns = {
            row[1]: {"type": row[2].lower(), "pk": row[5]}
            for row in conn.execute("pragma table_info(base_assistants)")
        }
        message_kinds_columns = {
            row[1]: {"type": row[2].lower(), "pk": row[5]}
            for row in conn.execute("pragma table_info(message_kinds)")
        }
        unique_user_indexes = [
            row[1] for row in conn.execute("pragma index_list(active_users)") if row[2]
        ]
        unique_user_index_columns = {
            index_name: [
                row[2] for row in conn.execute(f"pragma index_info({index_name})")
            ]
            for index_name in unique_user_indexes
        }

    assert {
        "active_users",
        "deleted_users",
        "threads",
        "messages",
        "message_kinds",
        "attachments",
    } <= names
    assert active_users_columns["id"] == {"type": "integer", "pk": 1}
    assert active_users_columns["suspended_at"]["type"] == "text"
    assert deleted_users_columns["id"] == {"type": "integer", "pk": 1}
    assert deleted_users_columns["login_name"]["type"] == "text"
    assert threads_columns["id"] == {"type": "text", "pk": 1}
    assert threads_columns["user_id"]["type"] == "integer"
    assert threads_columns["deleted_at"]["type"] == "text"
    assert messages_columns["id"] == {"type": "integer", "pk": 1}
    assert base_assistants_columns["allowed_file_extensions_json"]["type"] == "text"
    assert message_kinds_columns["id"] == {"type": "integer", "pk": 1}
    assert message_kinds_columns["message_id"]["type"] == "integer"
    assert message_kinds_columns["order_index"]["type"] == "integer"
    assert ["login_name"] in unique_user_index_columns.values()


def test_initialize_backfills_initial_setup_state_for_existing_admin(
    tmp_path: Path,
) -> None:
    # 観点: 完了状態導入前のDBに管理者がいれば起動時に一度だけ補完すること。
    # 目的: 既存DBで初期セットアップを再公開せず新しい状態表へ移行する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    with database.connect() as conn:
        AuthRepository(conn).create(
            login_name="owner",
            is_admin=True,
            password_hash="hash",
        )
        conn.commit()
        conn.execute("drop table initial_setup_state")
        conn.commit()

    database.initialize()
    database.initialize()

    with database.connect() as conn:
        completed = conn.execute(
            "select count(*) from initial_setup_state"
        ).fetchone()[0]

    assert completed == 1


def test_connect_enables_foreign_keys_and_row_factory(tmp_path: Path) -> None:
    """db_pathを受け取り、外部キー制約と列名アクセスできるSQLite接続を返す。"""
    # 観点: 接続設定
    # 目的: repository実装が依存するforeign keysとsqlite3.RowをDatabase.connectで保証する。
    db_path = tmp_path / "chat.sqlite3"
    database = Database(db_path)
    database.initialize()

    with database.connect() as conn:
        foreign_keys = conn.execute("pragma foreign_keys").fetchone()
        assert foreign_keys is not None
        assert foreign_keys[0] == 1

        conn.execute(
            """
            insert into active_users (
                id,
                login_name,
                password_hash,
                is_admin,
                created_at,
                updated_at
            ) values (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "alice",
                "hash",
                0,
                "2026-06-06T00:00:00+00:00",
                "2026-06-06T00:00:00+00:00",
            ),
        )
        row = conn.execute(
            "select login_name from active_users where id = ?",
            (1,),
        ).fetchone()

        assert isinstance(row, sqlite3.Row)
        assert row["login_name"] == "alice"

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                insert into threads (
                    id,
                    user_id,
                    title,
                    created_at,
                    updated_at
                ) values (?, ?, ?, ?, ?)
                """,
                (
                    "thread-1",
                    999,
                    "missing user",
                    "2026-06-06T00:00:00+00:00",
                    "2026-06-06T00:00:00+00:00",
                ),
            )


def test_connect_keeps_writes_transactional_until_commit(tmp_path: Path) -> None:
    """db_pathを受け取り、commit前の書き込みを別接続へ公開しない接続を返す。"""
    # 観点: トランザクション
    # 目的: Database.connect利用者が明示commitで永続化境界を制御できることを固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as write_conn:
        write_conn.execute(
            """
            insert into active_users (
                login_name,
                password_hash,
                is_admin,
                created_at,
                updated_at
            ) values (?, ?, ?, ?, ?)
            """,
            (
                "admin",
                "hash",
                1,
                "2026-06-06T00:00:00+00:00",
                "2026-06-06T00:00:00+00:00",
            ),
        )

        with database.connect() as read_conn:
            count_before_commit = read_conn.execute(
                "select count(*) from active_users"
            ).fetchone()[0]

        write_conn.commit()

    with database.connect() as read_conn:
        count_after_commit = read_conn.execute(
            "select count(*) from active_users"
        ).fetchone()[0]

    assert count_before_commit == 0
    assert count_after_commit == 1


def test_immediate_transaction_commits_and_rolls_back(tmp_path: Path) -> None:
    # 観点: 書き込みtransactionが即時ロックを取得し、成功時commit・失敗時rollbackすること。
    # 目的: 管理者状態の確認と更新を同一の直列化された境界へ閉じ込める。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.transaction() as conn:
        conn.execute(
            "insert into active_users(login_name, password_hash, created_at, updated_at) values (?, ?, ?, ?)",
            ("committed", "hash", "now", "now"),
        )

    with pytest.raises(RuntimeError):
        with database.transaction() as conn:
            conn.execute(
                "insert into active_users(login_name, password_hash, created_at, updated_at) values (?, ?, ?, ?)",
                ("rolled-back", "hash", "now", "now"),
            )
            raise RuntimeError("rollback")

    with database.connect() as conn:
        names = [row[0] for row in conn.execute("select login_name from active_users")]

    assert names == ["committed"]
