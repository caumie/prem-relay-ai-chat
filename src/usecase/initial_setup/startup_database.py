"""アプリ起動時のDB schema初期化と未完了応答の収束を担当する。"""

from ...infrastructure import MessageRepository
from . import InitialSetupUsecaseContext, initial_setup_usecase_context


def initialize_database_schema(
    *,
    context: InitialSetupUsecaseContext | None = None,
) -> None:
    """DB schemaを初期化する。

    Args:
        context: 初回セットアップ usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        None。

    起動時に永続化先の親ディレクトリと現在schemaを揃え、以後のusecaseが
    repositoryを実行できる状態にする。
    """
    ctx = context if context is not None else initial_setup_usecase_context()
    ctx.database.initialize()


def fail_processing_assistant_messages(
    *,
    context: InitialSetupUsecaseContext | None = None,
) -> None:
    """processing中のassistant messageをfailedへ収束する。

    Args:
        context: 初回セットアップ usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        None。

    再起動で処理継続できない assistant message を failed に落とし、
    ユーザーが再送や削除で回復できる状態にする。
    """
    ctx = context if context is not None else initial_setup_usecase_context()
    with ctx.database.connect() as conn:
        MessageRepository(conn).fail_processing_assistant_messages()
        conn.commit()
