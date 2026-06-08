"""Web route packageの公開入口を定義する。

このファイルはpackage外から見えるroute配線の入口を扱う。個別route moduleの
APIRouter取り込み、共通HTTP依存関係、各routerの設定をここへ集約する。
"""

import logging

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.templating import Jinja2Templates

from ..infrastructure import AttachmentStorage
from ..models import User
from ..service.response_service import ResponseService
from ..usecase.auth import get_current_user
from ..usecase.chat import build_chat_page
from ..usecase.context import UsecaseContext
from .admin import base_assistant as admin_base_assistant_routes
from .admin import user as admin_user_routes
from .admin import user_assistant as admin_user_assistant_routes
from . import assistant as assistant_routes
from . import chat as chat_routes
from . import auth as auth_routes
from .util.csrf import ensure_csrf_token

logger = logging.getLogger(__name__)


def register_web_routes(
    app: FastAPI,
    *,
    templates: Jinja2Templates,
    usecase_context: UsecaseContext,
    response_service: ResponseService,
    attachment_storage: AttachmentStorage,
) -> None:
    """Web route package全体をFastAPIアプリへ登録する。

    Args:
        app: routeを登録するFastAPIインスタンス。
        templates: HTML描画に使うJinja2Templates。
        usecase_context: usecase実行に渡す依存束。
        response_service: SSEイベント生成を担当するservice。
        attachment_storage: 添付ファイル保存を担当するstorage。

    Returns:
        None。

    package入口で個別route moduleの設定、共通dependency定義、router includeを
    行うことで、presentation層の配線責務をこの入口へまとめる。
    """
    async def current_user(request: Request) -> User:
        """セッションから現在ユーザーを取得する。

        Args:
            request: FastAPI request。SessionMiddlewareによりsessionを持つ。

        Returns:
            ログイン済みUser。

        Raises:
            HTTPException: 未ログインまたはユーザー欠落時は/loginへ303遷移。
        """
        user_id = request.session.get("user_id")
        user = (
            get_current_user(usecase_context, user_id=user_id)
            if isinstance(user_id, int)
            else None
        )
        if user is None:
            logger.warning("auth.required path=%s", request.url.path)
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/login"},
            )
        return user

    async def current_admin(user: User = Depends(current_user)) -> User:
        """現在ユーザーが管理者であることを検証する。

        Args:
            user: ログイン済みUser。

        Returns:
            管理者User。

        Raises:
            HTTPException: 一般ユーザーの場合は403。
        """
        if not user.is_admin:
            raise HTTPException(403)
        return user

    def shell_context(
        request: Request,
        user: User,
    ) -> dict[str, object]:
        """サイドバーを含む共通レイアウト用の基本contextを作る。

        Args:
            request: HTML描画対象のFastAPI request。
            user: ログイン済みUser。

        Returns:
            shellテンプレートへ渡す共通context。
        """
        page = build_chat_page(usecase_context, user_id=user.id)
        return {
            "request": request,
            "user": user,
            "thread": None,
            "threads": page.threads if page is not None else [],
            "csrf_token": ensure_csrf_token(request),
        }

    async def assistant_current_user(request: Request) -> User:
        """assistant router 用に Request から現在ユーザーを返す。"""
        return await current_user(request)

    async def assistant_current_admin(request: Request) -> User:
        """assistant router 用に Request から現在管理者を返す。"""
        return await current_admin(await current_user(request))

    auth_routes.templates = templates
    assistant_routes.templates = templates
    chat_routes.templates = templates
    admin_user_routes.templates = templates
    admin_base_assistant_routes.templates = templates
    admin_user_assistant_routes.templates = templates
    auth_routes.usecase_context = usecase_context

    assistant_routes.configure_assistant_routes(
        usecase_context=usecase_context,
        current_user=assistant_current_user,
        shell_context=shell_context,
    )
    admin_user_routes.configure_admin_user_routes(
        usecase_context=usecase_context,
        current_admin=assistant_current_admin,
        shell_context=shell_context,
    )
    admin_base_assistant_routes.configure_admin_base_assistant_routes(
        usecase_context=usecase_context,
        current_admin=assistant_current_admin,
        shell_context=shell_context,
    )
    admin_user_assistant_routes.configure_admin_user_assistant_routes(
        usecase_context=usecase_context,
        current_admin=assistant_current_admin,
        shell_context=shell_context,
    )
    chat_routes.configure_chat_routes(
        usecase_context=usecase_context,
        current_user=current_user,
        response_service=response_service,
        attachment_storage=attachment_storage,
    )

    app.include_router(auth_routes.router)
    app.include_router(assistant_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(admin_user_routes.router)
    app.include_router(admin_base_assistant_routes.router)
    app.include_router(admin_user_assistant_routes.router)
