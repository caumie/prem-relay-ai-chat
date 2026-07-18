"""admin user 更新ユースケースを担当する。"""

from ...service.password import hash_password
from ...infrastructure import AuthRepository
from ...models import User
from . import AdminUserUsecaseContext, admin_user_usecase_context
from .authorization import require_admin_actor, require_other_active_admin
from .errors import AdminUserNotFoundError


def update_user(
    *,
    user_id: int,
    login_name: str,
    password: str,
    is_admin: bool,
    actor: User,
    context: AdminUserUsecaseContext | None = None,
) -> User:
    """既存ユーザーを更新して返す。

    Args:
        user_id: 更新対象ユーザー ID。
        login_name: 更新後ログイン名。
        password: 空文字なら変更しない平文パスワード。
        is_admin: 更新後の管理者権限。
        actor: 操作を実行する現在の管理者。
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        更新済みユーザー。

    パスワード変更の有無と login 名整形を usecase に閉じるため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    with ctx.database.transaction() as conn:
        repo = AuthRepository(conn)
        require_admin_actor(repo, actor)
        existing = repo.get_user(user_id)
        if existing is None:
            raise AdminUserNotFoundError()
        target = User(
            id=user_id,
            login_name=login_name.strip(),
            is_admin=is_admin,
            suspended_at=existing.suspended_at,
        )
        if not target.is_admin:
            require_other_active_admin(repo, existing)
        return repo.update(
            target,
            password_hash=(
                hash_password(password, ctx.password_pepper) if password else None
            ),
        )
