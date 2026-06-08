"""assistant ユースケースの例外型を定義する。"""


class AssistantUsecaseError(Exception):
    """assistant 操作が権限や整合性の都合で成立しない場合の例外。"""
