"""添付ダウンロード対象の取得ユースケースを担当する。"""

from dataclasses import dataclass
from pathlib import Path

from ...infrastructure import AttachmentRepository
from ...models import Attachment
from . import ChatUsecaseContext, chat_usecase_context


@dataclass(frozen=True)
class AttachmentDownload:
    """添付ダウンロードに必要な解決済み情報を表す。

    Args:
        path: 実ファイルの解決済みパス。
        media_type: HTTP レスポンスへ渡す MIME type。
        filename: ダウンロード時に提示する元ファイル名。
    """

    path: Path
    media_type: str
    filename: str


def get_attachment(
    *,
    attachment_id: str,
    user_id: int,
    context: ChatUsecaseContext | None = None,
) -> Attachment | None:
    """所有者検証付きで添付metadataを取得する。

    Args:
        attachment_id: 取得対象の添付ID。
        user_id: 所有者として検証するユーザーID。

    Returns:
        所有者が一致するAttachment。見つからなければNone。

    presentationがAttachmentRepositoryを直接扱わないようにするため。
    """
    ctx = context if context is not None else chat_usecase_context()
    with ctx.database.connect() as conn:
        return AttachmentRepository(conn).get_for_user(
            attachment_id=attachment_id,
            user_id=user_id,
        )


def get_attachment_download(
    *,
    attachment_id: str,
    user_id: int,
    context: ChatUsecaseContext | None = None,
) -> AttachmentDownload | None:
    """所有者検証済み添付のダウンロード情報を返す。

    Args:
        attachment_id: 取得対象の添付ID。
        user_id: 所有者として検証するユーザーID。
        context: chat usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        所有者が一致する添付のダウンロード情報。見つからなければNone。

    presentation が保存相対パスの解決や storage 参照を直接持たないようにする。
    """
    ctx = context if context is not None else chat_usecase_context()
    attachment = get_attachment(
        attachment_id=attachment_id,
        user_id=user_id,
        context=ctx,
    )
    if attachment is None:
        return None
    return AttachmentDownload(
        path=ctx.attachment_storage.resolve(attachment.stored_path),
        media_type=attachment.content_type,
        filename=attachment.original_filename,
    )
