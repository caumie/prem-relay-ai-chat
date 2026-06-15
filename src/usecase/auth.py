"""認証ユースケース群の公開入口と実装を担当する。"""

from dataclasses import dataclass

from ..service.password import verify_password
from ..infrastructure import AuthRepository, Database
from ..models import User
from . import runtime


@dataclass(frozen=True)
class AuthUsecaseContext:
    """認証 usecase の実行依存を表す。

    Args:
        database: ユーザー認証情報を読む Database。
        password_pepper: パスワード検証に使う追加秘密値。
    """

    database: Database
    password_pepper: str


def auth_usecase_context() -> AuthUsecaseContext:
    """認証 usecase 用 context を返す。

    Returns:
        認証 usecase が使う Database と password_pepper だけを含む context。

    共有 runtime から認証 usecase に必要な依存だけを取り出し、
    認証以外の依存へ触れない形にする。
    """
    usecase_runtime = runtime.get_usecase_runtime()
    return AuthUsecaseContext(
        database=usecase_runtime.database,
        password_pepper=usecase_runtime.config.password_pepper,
    )


def challenge(
    *,
    login_name: str,
    password: str,
    context: AuthUsecaseContext | None = None,
) -> User | None:
    """ログイン名とパスワードでユーザーを認証する。

    Args:
        login_name: フォームから受け取ったログイン名。
        password: フォームから受け取った平文パスワード。
        context: 認証 usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        認証できたUser、失敗時はNone。

    presentation が認証可否やハッシュ照合の詳細を持たずに済むようにする。
    """
    ctx = context if context is not None else auth_usecase_context()
    with ctx.database.connect() as conn:
        repo = AuthRepository(conn)
        user = repo.get_by_login_name(login_name)
        if user is None or user.suspended_at is not None:
            return None
        password_hash = repo.get_password_hash_by_login_name(login_name)
        if password_hash is None:
            return None
        if not verify_password(password, password_hash, ctx.password_pepper):
            return None
        return user


def get_current_user(
    *, user_id: int, context: AuthUsecaseContext | None = None
) -> User | None:
    """セッションに保存された user_id から現在ユーザーを取得する。

    Args:
        user_id: セッションから取り出したユーザーID。
        context: 認証 usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        存在するUser、欠落または休止中ならNone。

    presentation がセッション内IDの有効性判断を直接持たずに済むようにする。
    """
    ctx = context if context is not None else auth_usecase_context()
    with ctx.database.connect() as conn:
        user = AuthRepository(conn).get_user(user_id)
        if user is None or user.suspended_at is not None:
            return None
        return user


__all__ = [
    "AuthUsecaseContext",
    "auth_usecase_context",
    "challenge",
    "get_current_user",
]
