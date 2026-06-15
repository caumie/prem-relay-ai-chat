"""admin user 削除ユースケースを担当する。"""

from ...infrastructure import (
    AttachmentRepository,
    AuthRepository,
    ThreadRepository,
    UserAssistantRepository,
)
from . import AdminUserUsecaseContext, admin_user_usecase_context


def delete_user(
    *, user_id: int, context: AdminUserUsecaseContext | None = None
) -> bool:
    """関連データと添付を含めて user を物理削除する。

    Args:
        user_id: 削除対象ユーザー ID。
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        削除に成功したら True、対象がなければ False。

    user ぶら下がりデータと保存ファイルの整合を保って削除するため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    storage = ctx.attachment_storage
    with ctx.database.connect() as conn:
        attachments = AttachmentRepository(conn).list_by_user(user_id)
        for attachment in attachments:
            storage.delete(attachment.stored_path)
        AttachmentRepository(conn).physical_delete_by_user(user_id)
        ThreadRepository(conn).physical_delete_by_user(user_id)
        UserAssistantRepository(conn).physical_delete_by_owner(user_id)
        deleted = AuthRepository(conn).delete_user(user_id)
        conn.commit()
        return deleted
