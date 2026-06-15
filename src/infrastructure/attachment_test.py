"""AttachmentRepositoryの所有者付き取得責務を検証する。"""

import sqlite3
from pathlib import Path
from uuid import uuid4

from src.service.password import hash_password
from src.models import Attachment, User
from src.infrastructure import AttachmentRepository, Database
from src.infrastructure import AuthRepository, utcnow


def test_attachment_repository_saves_and_reads_owned_attachment(
    tmp_path: Path,
) -> None:
    # 観点: Attachmentモデルを保存し、所有者条件付きで取得できること。
    # 目的: 添付metadataの所有者境界をRepositoryで固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        other = save_user(conn, "pepper", "other", "otherpass")
        repo = AttachmentRepository(conn)
        attachment = save_attachment(
            conn,
            user_id=user.id,
            original_filename="photo.png",
            stored_path=f"{user.id}/photo.png",
            content_type="image/png",
            size_bytes=123,
            sha256="abc",
        )
        owned = repo.get_for_user(
            attachment_id=attachment.id,
            user_id=user.id,
        )
        rejected = repo.get_for_user(
            attachment_id=attachment.id,
            user_id=other.id,
        )
        conn.commit()

    assert owned == attachment
    assert rejected is None


def save_user(
    conn: sqlite3.Connection,
    password_pepper: str,
    login_name: str,
    password: str,
) -> User:
    return AuthRepository(conn).create(
        login_name=login_name,
        is_admin=False,
        password_hash=hash_password(password, password_pepper),
    )


def save_attachment(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    original_filename: str,
    stored_path: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
) -> Attachment:
    return AttachmentRepository(conn).save(
        Attachment(
            id=str(uuid4()),
            user_id=user_id,
            original_filename=original_filename,
            stored_path=stored_path,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            created_at=utcnow(),
        )
    )
