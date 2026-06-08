"""添付ダウンロード対象の取得ユースケースを担当する。"""

from ...infrastructure import AttachmentRepository
from ...models import Attachment
from ..context import UsecaseContext


def get_attachment(
    context: UsecaseContext, *, attachment_id: str, user_id: int
) -> Attachment | None:
    """所有者検証付きで添付metadataを取得する。

    Args:
        attachment_id: 取得対象の添付ID。
        user_id: 所有者として検証するユーザーID。

    Returns:
        所有者が一致するAttachment。見つからなければNone。

    presentationがAttachmentRepositoryを直接扱わないようにするため。
    """
    with context.database.connect() as conn:
        return AttachmentRepository(conn).get_for_user(
            attachment_id=attachment_id,
            user_id=user_id,
        )
