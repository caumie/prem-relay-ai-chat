"""FastAPIアプリの生成と各層の配線を担当する。

このファイルは設定読み込み、ログ設定、DB初期化、service生成、middleware、
static mount、web route登録だけを扱う。HTTP routeの詳細、チャット操作、
認証処理、LLM接続処理はそれぞれの責務ファイルへ委譲する。
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .app_logger import configure_logging
from .config import AppConfig, load_app_config, load_connection_providers
from .llm.client import OpenAIResponder
from .infrastructure import (
    AttachmentStorage,
    Database,
    MessageRepository,
)
from .service.response_service import Responder, ResponseService
from .presentation import register_web_routes
from .presentation.util.csrf import CsrfTokenMiddleware
from .usecase.admin_user.bootstrap_admin import bootstrap_admin
from .usecase.context import UsecaseContext

logger = logging.getLogger(__name__)


def build_app(
    config: AppConfig | None = None, responder: Responder | None = None
) -> FastAPI:
    """FastAPIアプリを生成し、必要な依存オブジェクトを配線する。

    Args:
        config: テストや起動時に指定できるアプリ設定。Noneなら既定値。
        responder: LLM応答生成境界。NoneならOpenAIResponder。

    Returns:
        route、middleware、static mountを登録済みのFastAPIアプリ。

    アプリ生成時点でDBを初期化し、未完了assistant messageはfailedへ収束する。
    これはユーザーが明示的に再送/削除でリカバーする方針に合わせた起動処理。
    """
    cfg = config or load_app_config()
    configure_logging(cfg)
    secret = cfg.session_secret
    database = Database(cfg.db_path)
    templates = Jinja2Templates(directory=str(cfg.templates_dir))
    llm = responder or OpenAIResponder()
    response_service = ResponseService(database=database, responder=llm)
    attachment_storage = AttachmentStorage(cfg.uploads_dir)
    usecase_context = UsecaseContext(
        database=database,
        password_pepper=secret,
        load_connection_providers=lambda: load_connection_providers(cfg.data_dir),
        response_service=response_service,
        uploads_dir=cfg.uploads_dir,
        attachment_storage=attachment_storage,
    )
    _initialize_runtime_state(
        context=usecase_context,
        admin_login_name=cfg.admin_login_name,
        admin_password=cfg.admin_password,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """FastAPI lifespanで起動時DB状態を再確認する。

        Args:
            app: FastAPIから渡されるアプリインスタンス。

        Yields:
            起動中の制御。
        """
        logger.info("app.start db_path=%s data_dir=%s", cfg.db_path, cfg.data_dir)
        _initialize_runtime_state(
            context=usecase_context,
            admin_login_name=cfg.admin_login_name,
            admin_password=cfg.admin_password,
        )
        yield
        logger.info("app.stop")

    app = FastAPI(lifespan=lifespan)
    app.state.database = database
    app.state.config = cfg
    app.state.usecase_context = usecase_context
    app.state.responder = llm
    app.state.response_service = response_service
    app.state.attachment_storage = attachment_storage
    app.add_middleware(CsrfTokenMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie=cfg.session_cookie_name,
        same_site="lax",
        https_only=False,
    )
    app.mount("/static", StaticFiles(directory=cfg.static_dir), name="static")
    app.mount("/assets", StaticFiles(directory=cfg.static_dir), name="assets")
    register_web_routes(
        app,
        templates=templates,
        usecase_context=usecase_context,
        response_service=response_service,
        attachment_storage=attachment_storage,
    )
    return app


def _initialize_runtime_state(
    *,
    context: UsecaseContext,
    admin_login_name: str,
    admin_password: str,
) -> None:
    """DB初期化、初期管理者作成、未完了応答のfailed収束を行う。

    Args:
        context: 初期化対象Databaseを含むusecase context。
        admin_login_name: 初期管理者ログイン名。
        admin_password: 初期管理者パスワード。
    Returns:
        None。
    """
    context.database.initialize()
    bootstrap_admin(
        context,
        login_name=admin_login_name,
        password=admin_password,
    )
    with context.database.connect() as conn:
        MessageRepository(conn).fail_processing_assistant_messages()
        conn.commit()


app = build_app()
