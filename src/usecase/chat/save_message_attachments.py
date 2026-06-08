"""チャット投稿時の添付保存ユースケースを担当する。"""

import sqlite3
from uuid import uuid4

from ...infrastructure import AttachmentRepository, MAX_ATTACHMENTS_PER_MESSAGE, utcnow
from ...models import (
    Attachment,
    AssistantConfigValue,
    PendingUpload,
    UserInputError,
    default_assistant_file_extensions,
    normalize_file_extensions,
)
from ..assistant import resolve_runtime_assistant
from ..context import UsecaseContext


async def save_message_attachments(
    context: UsecaseContext,
    *,
    user_id: int,
    assistant_id: str | None,
    uploads: list[PendingUpload],
    conn: sqlite3.Connection | None = None,
) -> list[Attachment]:
    """投稿フォームの未保存アップロードを保存し、Messageへ紐づけるAttachmentを返す。

    Args:
        user_id: 添付を所有するユーザーID。
        assistant_id: 投稿先assistant ID。
        uploads: presentation層でFastAPI型から変換した未保存アップロード一覧。
        conn: 既存transactionへ参加する場合のSQLite connection。Noneなら自前でcommitする。

    Returns:
        DBへ保存済みのAttachment一覧。

    Raises:
        UserInputError: assistant未指定、添付不可、件数超過、保存不可の場合。

    添付可否はassistant設定に属する業務判断なので、ファイル実体保存や
    metadata登録より前にusecaseで確定し、presentationへtransactionを漏らさない。
    """
    actual_uploads = [upload for upload in uploads if upload.filename]
    if not actual_uploads:
        return []
    if not assistant_id:
        raise UserInputError("assistant is required")
    assistant = resolve_runtime_assistant(
        context,
        user_id=user_id,
        assistant_id=assistant_id,
    )
    if not bool(assistant.config.get("allow_file_upload", False)):
        raise UserInputError("file upload is not allowed for this assistant")
    if len(actual_uploads) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise UserInputError("too many attachments")
    allowed_file_extensions = _allowed_file_extensions_from_config(
        assistant.config.get("allowed_file_extensions")
    )

    if conn is not None:
        return await _save_with_connection(
            context,
            user_id=user_id,
            uploads=actual_uploads,
            allowed_file_extensions=allowed_file_extensions,
            conn=conn,
        )
    with context.database.connect() as own_conn:
        attachments = await _save_with_connection(
            context,
            user_id=user_id,
            uploads=actual_uploads,
            allowed_file_extensions=allowed_file_extensions,
            conn=own_conn,
        )
        own_conn.commit()
        return attachments


async def _save_with_connection(
    context: UsecaseContext,
    *,
    user_id: int,
    uploads: list[PendingUpload],
    allowed_file_extensions: list[str],
    conn: sqlite3.Connection,
) -> list[Attachment]:
    """指定connectionのtransaction内で添付実体とmetadataを保存する。"""
    attachments: list[Attachment] = []
    storage = context.attachment_storage
    repo = AttachmentRepository(conn)
    for upload in uploads:
        stored = await storage.save(
            user_id=user_id,
            upload=upload,
            allowed_file_extensions=allowed_file_extensions,
        )
        attachments.append(
            repo.save(
                Attachment(
                    id=str(uuid4()),
                    user_id=user_id,
                    original_filename=stored.original_filename,
                    stored_path=stored.stored_path,
                    content_type=stored.content_type,
                    size_bytes=stored.size_bytes,
                    sha256=stored.sha256,
                    created_at=utcnow(),
                )
            )
        )
    return attachments


def _allowed_file_extensions_from_config(
    value: AssistantConfigValue | None,
) -> list[str]:
    """ResolvedAssistant設定から添付許可拡張子を取り出す。

    Args:
        value: assistant.config の allowed_file_extensions 値。

    Returns:
        dotなし小文字の許可拡張子一覧。未指定または空なら既定値。
    """
    if isinstance(value, list):
        normalized = normalize_file_extensions(
            [item for item in value if isinstance(item, str)]
        )
        if normalized:
            return normalized
    return default_assistant_file_extensions()
