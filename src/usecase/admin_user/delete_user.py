"""admin user 削除ユースケースを担当する。"""

from ...infrastructure import (
    AttachmentRepository,
    AuthRepository,
    ThreadRepository,
    UserAssistantRepository,
)
from ...models import User
from . import AdminUserUsecaseContext, admin_user_usecase_context
from .authorization import (
    reject_self_mutation,
    require_admin_actor,
    require_other_active_admin,
)
from .errors import AdminUserNotFoundError, LastActiveAdminError


def delete_user(
    *, user_id: int, actor: User, context: AdminUserUsecaseContext | None = None
) -> bool:
    """関連データと添付を含めて user を物理削除する。

    Args:
        user_id: 削除対象ユーザー ID。
        actor: 操作を実行する現在の管理者。
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        削除に成功したら True、対象がなければ False。

    user ぶら下がりデータと保存ファイルの整合を保って削除するため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    storage = ctx.attachment_storage
    with ctx.database.transaction() as conn:
        repo = AuthRepository(conn)
        current_actor = require_admin_actor(repo, actor)
        reject_self_mutation(current_actor, user_id)
        target = repo.get_user(user_id)
        if target is None:
            raise AdminUserNotFoundError()
        require_other_active_admin(repo, target)
        attachments = AttachmentRepository(conn).list_by_user(user_id)
        deleted = repo.delete_user(user_id)
        if not deleted:
            raise LastActiveAdminError()
        AttachmentRepository(conn).physical_delete_by_user(user_id)
        ThreadRepository(conn).physical_delete_by_user(user_id)
        UserAssistantRepository(conn).physical_delete_by_owner(user_id)

    for attachment in attachments:
        storage.delete(attachment.stored_path)
    return deleted
