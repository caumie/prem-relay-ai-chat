"""admin user 作成ユースケースを担当する。"""

from ...auth_password import hash_password
from ...infrastructure import AuthRepository
from ...models import User
from ..context import UsecaseContext


def create_user(
    context: UsecaseContext, *, login_name: str, password: str, is_admin: bool
) -> User:
    """新しいユーザーを作成して返す。

    Args:
        login_name: 作成するログイン名。
        password: 保存前にハッシュ化する平文パスワード。
        is_admin: 管理者権限を付与するかどうか。

    Returns:
        保存済みユーザー。

    login 名の整形とパスワードハッシュ生成を usecase 側で閉じるため。
    """
    with context.database.connect() as conn:
        user = AuthRepository(conn).save(
            User(id=0, login_name=login_name.strip(), is_admin=is_admin),
            password_hash=hash_password(password, context.password_pepper),
        )
        conn.commit()
        return user
