"""管理ユーザー操作に共通するactor認可を担当する。"""

from ...infrastructure import AuthRepository
from ...models import User
from .errors import (
    AdminUserPermissionError,
    CannotModifyCurrentAdminError,
    LastActiveAdminError,
)


def require_admin_actor(repo: AuthRepository, actor: User) -> User:
    """DB上で現在有効な管理者actorを確認して返す。"""
    current = repo.get_user(actor.id)
    if current is None or not current.is_admin or current.suspended_at is not None:
        raise AdminUserPermissionError()
    return current


def reject_self_mutation(actor: User, user_id: int) -> None:
    """停止・削除対象がactor自身なら拒否する。"""
    if actor.id == user_id:
        raise CannotModifyCurrentAdminError()


def require_other_active_admin(repo: AuthRepository, target: User) -> None:
    """有効管理者を無効化する場合に別の管理者がいることを確認する。"""
    if target.is_admin and target.suspended_at is None and not repo.has_other_active_admin(
        target.id
    ):
        raise LastActiveAdminError()
