"""FastAPIアプリの生成と各層の配線を担当する。

このファイルは設定読み込み、ログ設定、DB初期化、service生成、middleware、
static mount、web route登録だけを扱う。HTTP routeの詳細、チャット操作、
認証処理、LLM接続処理はそれぞれの責務ファイルへ委譲する。
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse

from .app_logger import configure_logging, reset_request_id, set_request_id
from .config import AppConfig, load_app_config
from .presentation import register_web_routes
from .presentation.runtime import init_presentation_runtime
from .presentation.util.csrf import CsrfTokenMiddleware
from .service.response_service import Responder
from .usecase.initial_setup import (
    fail_processing_assistant_messages,
    initialize_database_schema,
)
from .usecase.runtime import init_usecase_runtime

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
    init_usecase_runtime(config=cfg, responder=responder)
    init_presentation_runtime(
        templates=Jinja2Templates(directory=str(cfg.templates_dir))
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

        logger.info("app.init.database.start")
        try:
            initialize_database_schema()
        except Exception:
            logger.error("app.init.database.failed")
            raise
        logger.info("app.init.database.done")
        logger.info("app.init.recovery.start")
        try:
            # Job所有権を永続化していないため、全processingの回収は正式構成の
            # 単一worker起動時だけ安全である。複数workerへ広げる場合は
            # lease/fencingを先に導入し、別processの実行中Jobを保護する。
            fail_processing_assistant_messages()
        except Exception:
            logger.error("app.init.recovery.failed")
            raise
        logger.info("app.init.recovery.done")

        yield

        logger.info("app.stop")

    app = FastAPI(lifespan=lifespan)

    # TODO: 配備方式に合わせたCSP、X-Content-Type-Options、Referrer-Policyなどを
    # 全responseへ付与するsecurity headers middlewareを追加する。

    async def request_id_middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> StarletteResponse:
        """各HTTP requestへ相関IDを割り当てる。

        Args:
            request: 受信したHTTP request。
            call_next: 次の middleware または route handler。

        Returns:
            request_id を付与したHTTP response。

        logging filter が暗黙状態へ依存しすぎないよう、HTTP 境界で
        request_id を生成して response header へも返す。
        """
        request_id = uuid4().hex
        token = set_request_id(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers["X-Request-ID"] = request_id
        return response

    app.middleware("http")(request_id_middleware)

    app.add_middleware(CsrfTokenMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie=cfg.session_cookie_name,
        same_site="lax",
        https_only=cfg.session_cookie_secure,
    )
    app.mount("/static", StaticFiles(directory=cfg.static_dir), name="static")
    register_web_routes(app)
    return app
