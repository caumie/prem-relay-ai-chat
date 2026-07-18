"""presentation 層の共通 dependency/context を定義する。

このファイルは router 間で共有する現在ユーザー取得、管理者検証、
共通テンプレート context、template 取得をまとめる。HTTP request に依存する
presentation 固有の処理だけを持ち、認証・チャット操作の永続化詳細は usecase へ委譲する。
"""

import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates

from ..models import User
from ..usecase.auth import get_current_user
from ..usecase.chat import build_chat_page
from .runtime import get_presentation_runtime
from .util.csrf import ensure_csrf_token

logger = logging.getLogger(__name__)


def presentation_templates() -> Jinja2Templates:
    """共有 presentation runtime が保持する templates を返す。

    Returns:
        HTML 描画に使う Jinja2Templates。

    router が module global を持たずに templates を取得できるようにする。
    """
    return get_presentation_runtime().templates


async def current_user(request: Request) -> User:
    """セッションから現在ユーザーを取得する。

    Args:
        request: SessionMiddleware 適用済みの FastAPI request。

    Returns:
        ログイン済み User。

    Raises:
        HTTPException: 未ログインまたはユーザー欠落時は `/login` へ 303 遷移する。
    """
    user_id = request.session.get("user_id")
    user = get_current_user(user_id=user_id) if isinstance(user_id, int) else None
    if user is None:
        logger.warning(
            "auth.required path=%s method=%s request_type=%s",
            request.url.path,
            request.method,
            _request_type(request),
        )
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


async def current_admin(user: User = Depends(current_user)) -> User:
    """現在ユーザーが管理者であることを検証する。

    Args:
        user: ログイン済み User。

    Returns:
        管理者 User。

    Raises:
        HTTPException: 一般ユーザーの場合は 403。
    """
    if not user.is_admin:
        raise HTTPException(403)
    return user


def shell_context(request: Request, user: User) -> dict[str, object]:
    """サイドバーを含む共通レイアウト用の基本 context を返す。

    Args:
        request: HTML 描画対象の FastAPI request。
        user: ログイン済み User。

    Returns:
        shell テンプレートへ渡す共通 context。
    """
    page = build_chat_page(user_id=user.id)
    return {
        "request": request,
        "user": user,
        "thread": None,
        "threads": page.threads if page is not None else [],
        "csrf_token": ensure_csrf_token(request),
    }


def _request_type(request: Request) -> str:
    """HTTP request の種別をざっくり分類する。"""
    if request.headers.get("HX-Request") == "true":
        return "htmx"
    if "text/event-stream" in request.headers.get("accept", ""):
        return "sse"
    return "html"
