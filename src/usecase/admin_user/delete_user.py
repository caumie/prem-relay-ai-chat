"""admin user 削除ユースケースを担当する。"""

from ...infrastructure import (
    AttachmentRepository,
    AuthRepository,
    ThreadRepository,
    UserAssistantRepository,
)
from ..context import UsecaseContext


def delete_user(context: UsecaseContext, *, user_id: int) -> bool:
    """関連データと添付を含めて user を物理削除する。

    Args:
        user_id: 削除対象ユーザー ID。

    Returns:
        削除に成功したら True、対象がなければ False。

    user ぶら下がりデータと保存ファイルの整合を保って削除するため。
    """
    storage = context.attachment_storage
    with context.database.connect() as conn:
        attachments = AttachmentRepository(conn).list_by_user(user_id)
        for attachment in attachments:
            storage.resolve(attachment.stored_path).unlink(missing_ok=True)
        AttachmentRepository(conn).physical_delete_by_user(user_id)
        ThreadRepository(conn).physical_delete_by_user(user_id)
        UserAssistantRepository(conn).physical_delete_by_owner(user_id)
        deleted = AuthRepository(conn).delete_user(user_id)
        conn.commit()
        return deleted
