"""admin base assistant 向け接続先一覧取得ユースケースを担当する。"""

from ...models import ConnectionProvider
from ..context import UsecaseContext


def list_connection_providers(context: UsecaseContext) -> list[ConnectionProvider]:
    """編集画面で選択できる接続先 Provider 一覧を返す。

    Args:
        なし。

    Returns:
        利用可能な接続先定義一覧。

    admin 管理画面の provider 選択肢をこのユースケースから返すため。
    """
    return context.load_connection_providers()
