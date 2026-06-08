"""admin user 休止ユースケースを担当する。"""

from ...infrastructure import AuthRepository
from ..context import UsecaseContext


def suspend_user(context: UsecaseContext, *, user_id: int) -> bool:
    """対象ユーザーを休止する。

    Args:
        user_id: 休止対象ユーザー ID。

    Returns:
        休止に成功したら True、対象がなければ False。

    管理操作の結果を route で単純に扱える契約へそろえるため。
    """
    with context.database.connect() as conn:
        suspended = AuthRepository(conn).suspend_user(user_id)
        conn.commit()
        return suspended
