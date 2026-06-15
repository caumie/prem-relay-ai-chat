"""認証ユースケースの責務をまとめて検証する。"""

from pathlib import Path

from src.config import AppConfig
from src.infrastructure import AttachmentStorage, Database
from src.usecase.admin_user import AdminUserUsecaseContext, create_user, suspend_user
from src.usecase.auth import (
    AuthUsecaseContext,
    auth_usecase_context,
    challenge,
    get_current_user,
)
from src.usecase.runtime import init_usecase_runtime


class TestAuthUsecaseContext:
    """auth_usecase_context の依存抽出を検証する。"""

    def test_contains_only_auth_dependencies(self, tmp_path: Path) -> None:
        """共有runtimeから認証に必要な依存だけを取り出す。"""
        # 観点: 認証 usecase context がconfigの秘密値をpassword_pepperへ変換すること。
        # 目的: runtimeはconfigを保持し、認証だけが必要な依存名へ変換する境界を固定する。
        config = AppConfig(
            db_path=tmp_path / "chat.sqlite",
            data_dir=tmp_path,
            uploads_dir=tmp_path / "uploads",
            session_secret="session-secret",
            password_pepper="password-pepper",
        )
        runtime = init_usecase_runtime(config=config)

        context = auth_usecase_context()

        assert context == AuthUsecaseContext(
            database=runtime.database,
            password_pepper="password-pepper",
        )
        assert runtime.config == config
        assert not hasattr(context, "response_service")


class TestChallenge:
    """challenge ユースケースの認証判断を検証する。"""

    def test_returns_user_only_for_valid_password(self, tmp_path: Path) -> None:
        """正しいパスワードの場合だけ認証ユーザーを返す。"""
        # 観点: 正しいパスワードだけログインユーザーとして認証されること。
        # 目的: presentation が認証判断やハッシュ照合の詳細を知らずに usecase へ委譲できる境界を固定する。
        context = _context(tmp_path)
        create_user(
            login_name="user1",
            password="pass123",
            is_admin=False,
            context=_admin_context(context, tmp_path),
        )

        authenticated = challenge(
            login_name="user1",
            password="pass123",
            context=context,
        )
        rejected = challenge(
            login_name="user1",
            password="wrong",
            context=context,
        )

        assert authenticated is not None
        assert authenticated.login_name == "user1"
        assert rejected is None

    def test_rejects_suspended_user(self, tmp_path: Path) -> None:
        """休止中ユーザーはパスワードが正しくても認証しない。"""
        # 観点: 休止中ユーザーは正しいパスワードでも認証されないこと。
        # 目的: ログイン可否の業務判断が repository ではなく usecase にあることを固定する。
        context = _context(tmp_path)
        admin_context = _admin_context(context, tmp_path)
        created = create_user(
            login_name="user1",
            password="pass123",
            is_admin=False,
            context=admin_context,
        )
        suspend_user(user_id=created.id, context=admin_context)

        assert (
            challenge(
                login_name="user1",
                password="pass123",
                context=context,
            )
            is None
        )


class TestGetCurrentUser:
    """get_current_user ユースケースの取得判断を検証する。"""

    def test_returns_none_for_missing_user(self, tmp_path: Path) -> None:
        """存在するユーザーを返し、欠落したユーザーIDでは None を返す。"""
        # 観点: セッション内 user_id から現在ユーザーを取得でき、欠落時は None を返すこと。
        # 目的: presentation 層が認証状態の有無だけを扱える境界を固定する。
        context = _context(tmp_path)

        assert get_current_user(user_id=9999, context=context) is None

    def test_returns_existing_user(self, tmp_path: Path) -> None:
        """存在するユーザーIDでは現在ユーザーを返す。"""
        # 観点: セッション内 user_id が有効なら対応するユーザーを取得できること。
        # 目的: presentation 層がDB取得の詳細を持たずに現在ユーザーを扱える境界を固定する。
        context = _context(tmp_path)
        created = create_user(
            login_name="user1",
            password="pass123",
            is_admin=False,
            context=_admin_context(context, tmp_path),
        )

        assert get_current_user(user_id=created.id, context=context) == created

    def test_returns_none_for_suspended_user(self, tmp_path: Path) -> None:
        """休止中ユーザーは現在ユーザーとして扱わない。"""
        # 観点: 休止中ユーザーはセッションからも有効扱いにしないこと。
        # 目的: ログイン済みでも休止後はアクセスを止められる境界を固定する。
        context = _context(tmp_path)
        admin_context = _admin_context(context, tmp_path)
        created = create_user(
            login_name="user1",
            password="pass123",
            is_admin=False,
            context=admin_context,
        )
        suspend_user(user_id=created.id, context=admin_context)

        assert get_current_user(user_id=created.id, context=context) is None


def _context(tmp_path: Path) -> AuthUsecaseContext:
    """認証用のテストcontextを初期化して返す。

    Args:
        tmp_path: テストごとの一時ディレクトリ。

    Returns:
        初期化済みDatabaseと固定pepperを持つ認証context。

    認証ユースケースが必要とする依存だけで検証できるようにする。
    """
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    return AuthUsecaseContext(
        database=database,
        password_pepper="pepper",
    )


def _admin_context(context: AuthUsecaseContext, tmp_path: Path) -> AdminUserUsecaseContext:
    """認証テストの状態作成に使うadmin user contextを返す。

    Args:
        context: 認証ユースケース用context。
        tmp_path: テストごとの一時ディレクトリ。

    Returns:
        同じDatabaseとpepperを持つadmin user context。

    ユーザー保存形式を独自実装せず、管理ユーザー作成ユースケースへ委譲する。
    """
    return AdminUserUsecaseContext(
        database=context.database,
        password_pepper=context.password_pepper,
        attachment_storage=AttachmentStorage(tmp_path / "uploads"),
    )
