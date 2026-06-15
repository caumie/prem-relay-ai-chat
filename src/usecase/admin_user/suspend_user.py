"""admin user 休止ユースケースを担当する。"""

from ...infrastructure import AuthRepository
from . import AdminUserUsecaseContext, admin_user_usecase_context


def suspend_user(
    *, user_id: int, context: AdminUserUsecaseContext | None = None
) -> bool:
    """対象ユーザーを休止する。

    Args:
        user_id: 休止対象ユーザー ID。
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        休止に成功したら True、対象がなければ False。

    管理操作の結果を route で単純に扱える契約へそろえるため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    with ctx.database.connect() as conn:
        suspended = AuthRepository(conn).suspend_user(user_id)
        conn.commit()
        return suspended
