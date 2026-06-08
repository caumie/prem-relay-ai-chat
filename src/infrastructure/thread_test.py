"""ThreadRepositoryの所有者付き保存責務を検証する。"""

import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.auth_password import hash_password
from src.models import Thread, User
from src.infrastructure import AuthRepository, Database, ThreadRepository, utcnow


def test_thread_repository_saves_updates_and_reads_owned_thread(tmp_path: Path) -> None:
    # 観点: Threadモデルを保存し、所有者条件付きで更新と取得ができること。
    # 目的: チャットスレッドの所有者境界をRepositoryで固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        thread = save_thread(conn, user.id, "title")
        repo = ThreadRepository(conn)
        renamed = repo.update(replace(thread, title="renamed", updated_at=utcnow()))
        loaded = repo.get(thread.id, user.id)
        conn.commit()

    assert renamed is not None
    assert renamed.title == "renamed"
    assert loaded == renamed


def save_user(
    conn: sqlite3.Connection,
    password_pepper: str,
    login_name: str,
    password: str,
) -> User:
    return AuthRepository(conn).save(
        User(id=0, login_name=login_name),
        password_hash=hash_password(password, password_pepper),
    )


def save_thread(conn: sqlite3.Connection, user_id: int, title: str) -> Thread:
    now = utcnow()
    return ThreadRepository(conn).save(
        Thread(
            id=str(uuid4()),
            user_id=user_id,
            title=title.strip()[:80] or "New chat",
            created_at=now,
            updated_at=now,
        )
    )
