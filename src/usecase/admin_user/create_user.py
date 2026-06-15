"""admin user 作成ユースケースを担当する。"""

from ...service.password import hash_password
from ...infrastructure import AuthRepository
from ...models import User
from . import AdminUserUsecaseContext, admin_user_usecase_context


def create_user(
    *,
    login_name: str,
    password: str,
    is_admin: bool,
    context: AdminUserUsecaseContext | None = None,
) -> User:
    """新しいユーザーを作成して返す。

    Args:
        login_name: 作成するログイン名。
        password: 保存前にハッシュ化する平文パスワード。
        is_admin: 管理者権限を付与するかどうか。
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        保存済みユーザー。

    login 名の整形とパスワードハッシュ生成を usecase 側で閉じるため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    with ctx.database.connect() as conn:
        user = AuthRepository(conn).create(
            login_name=login_name.strip(),
            is_admin=is_admin,
            password_hash=hash_password(password, ctx.password_pepper),
        )
        conn.commit()
        return user
