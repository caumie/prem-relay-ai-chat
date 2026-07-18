"""usecase 実行依存の初期化を担当する。

このファイルは FastAPI に依存せず、usecase が実行時に必要とする
長寿命依存を保持する。
"""

from collections.abc import Callable
from dataclasses import dataclass

from ..config import AppConfig, load_app_config, load_connection_providers
from ..infrastructure import AttachmentStorage, Database
from ..llm.client import OpenAIResponder
from ..models import ConnectionProvider
from ..service.response_service import Responder, ResponseService


@dataclass(frozen=True)
class UsecaseRuntime:
    """usecase 全体で共有する長寿命依存を保持する。

    Args:
        database: 永続化に使う Database。
        config: usecase の実行時依存を組み立てた元のアプリ設定。
        response_service: このworker process内だけでJobを所有する応答service。
        attachment_storage: 添付ファイル実体の保存・解決境界。
        load_connection_providers: 接続先定義を読み込む関数。
    """

    database: Database
    config: AppConfig
    response_service: ResponseService
    attachment_storage: AttachmentStorage
    load_connection_providers: Callable[[], list[ConnectionProvider]]


runtime: UsecaseRuntime | None = None


def init_usecase_runtime(
    *, config: AppConfig | None = None, responder: Responder | None = None
) -> UsecaseRuntime:
    """usecase runtime を初期化して返す。

    Args:
        config: usecase runtime の生成に使うアプリ設定。Noneなら既定設定を読み込む。
        responder: LLM応答生成境界。NoneならOpenAIResponderを使う。

    Returns:
        初期化した UsecaseRuntime。

    appのworker processごとに起動時一度だけ呼ぶ。Databaseと設定を共有runtimeへ
    集約し、usecase側は各領域のcontext経由で必要な依存へ変換して読む。
    ResponseServiceのJob Storeはprocess-localであり、worker間では共有しない。
    """
    global runtime
    cfg = config if config is not None else load_app_config()
    database = Database(cfg.db_path)
    runtime = UsecaseRuntime(
        config=cfg,
        database=database,
        response_service=ResponseService(
            database=database,
            responder=responder or OpenAIResponder(),
        ),
        attachment_storage=AttachmentStorage(cfg.uploads_dir),
        load_connection_providers=lambda: load_connection_providers(cfg.data_dir),
    )
    return runtime


def get_usecase_runtime() -> UsecaseRuntime:
    """初期化済みの共有 usecase runtime を返す。

    Args:
        なし。

    Returns:
        app起動時に初期化済みの UsecaseRuntime。

    usecaseやテストが module global を直接読まず、未初期化状態を明示的な
    RuntimeError として扱えるようにする。
    """
    if runtime is None:
        raise RuntimeError("usecase runtime is not initialized")
    return runtime
