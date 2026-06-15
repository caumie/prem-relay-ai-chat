"""初回セットアップ状態取得ユースケースを担当する。"""

from dataclasses import dataclass

from ...infrastructure import AuthRepository
from . import InitialSetupUsecaseContext, initial_setup_usecase_context


@dataclass(frozen=True)
class InitialSetupStatus:
    """初回管理者作成画面の表示可否を表す。

    Args:
        can_create_initial_admin: 初回管理者を作成できる場合はTrue。
    """

    can_create_initial_admin: bool


def get_initial_setup_status(
    *,
    context: InitialSetupUsecaseContext | None = None,
) -> InitialSetupStatus:
    """初回管理者作成が可能か返す。

    Args:
        context: 初回セットアップ usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        初回管理者作成画面の表示可否。

    route が認証テーブル構造を知らずに、未ログインのセットアップ導線を判断できるようにするため。
    """
    ctx = context if context is not None else initial_setup_usecase_context()
    with ctx.database.connect() as conn:
        has_admin = AuthRepository(conn).has_admin_user()
    return InitialSetupStatus(can_create_initial_admin=not has_admin)
