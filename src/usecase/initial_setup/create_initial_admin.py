"""初回管理者作成ユースケースを担当する。"""

from ...service.password import hash_password
from ...infrastructure import AuthRepository
from ...models import User
from . import InitialSetupUsecaseContext, initial_setup_usecase_context


class InitialAdminAlreadyExistsError(Exception):
    """初回管理者作成済みの場合に送出する例外。"""


def create_initial_admin(
    *,
    login_name: str,
    password: str,
    context: InitialSetupUsecaseContext | None = None,
) -> User:
    """最初の管理者ユーザーを作成して返す。

    Args:
        login_name: 作成する管理者ログイン名。
        password: 保存前にハッシュ化する平文パスワード。
        context: 初回セットアップ usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        保存済み管理者ユーザー。

    Raises:
        InitialAdminAlreadyExistsError: 既に管理者ユーザーが存在する場合。

    未ログインのセットアップ画面が管理者権限付与やパスワード保存形式を知らず、
    最初の管理者作成だけを委譲できるようにするため。
    """
    ctx = context if context is not None else initial_setup_usecase_context()
    with ctx.database.transaction() as conn:
        repo = AuthRepository(conn)
        if repo.is_initial_setup_completed():
            raise InitialAdminAlreadyExistsError()
        if repo.has_admin_user():
            raise InitialAdminAlreadyExistsError()
        user = repo.create(
            login_name=login_name.strip(),
            is_admin=True,
            password_hash=hash_password(password, ctx.password_pepper),
        )
        repo.mark_initial_setup_completed()
        return user
