"""admin user 休止ユースケースを担当する。"""

from ...infrastructure import AuthRepository
from ...models import User
from . import AdminUserUsecaseContext, admin_user_usecase_context
from .authorization import (
    reject_self_mutation,
    require_admin_actor,
    require_other_active_admin,
)
from .errors import AdminUserNotFoundError


def suspend_user(
    *, user_id: int, actor: User, context: AdminUserUsecaseContext | None = None
) -> bool:
    """対象ユーザーを休止する。

    Args:
        user_id: 休止対象ユーザー ID。
        actor: 操作を実行する現在の管理者。
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        休止に成功したら True、対象がなければ False。

    管理操作の結果を route で単純に扱える契約へそろえるため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    with ctx.database.transaction() as conn:
        repo = AuthRepository(conn)
        current_actor = require_admin_actor(repo, actor)
        reject_self_mutation(current_actor, user_id)
        target = repo.get_user(user_id)
        if target is None:
            raise AdminUserNotFoundError()
        require_other_active_admin(repo, target)
        return repo.suspend_user(user_id)
