"""管理ユーザー操作の業務例外を定義する。"""


class AdminUserError(Exception):
    """管理ユーザー操作の基底例外。"""


class AdminUserPermissionError(AdminUserError):
    """actorに管理ユーザー操作権限がない。"""


class AdminUserNotFoundError(AdminUserError):
    """対象ユーザーが存在しない。"""


class LastActiveAdminError(AdminUserError):
    """最後の有効管理者を失う操作が要求された。"""


class CannotModifyCurrentAdminError(AdminUserError):
    """現在のactor自身を停止・削除しようとした。"""
