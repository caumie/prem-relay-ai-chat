
"""CSRFトークンの生成、保持、検証を扱うHTTP境界ヘルパー。"""

import secrets
from typing import Annotated

from fastapi import Form, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "_csrf_token"
CSRF_TOKEN_BYTES = 32
CSRF_EXCLUDED_PATH_PREFIXES = ("/static/", "/assets/")


def ensure_csrf_token(request: Request) -> str:
    """セッションにCSRFトークンがなければ生成し、現在の値を返す。"""
    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = _new_csrf_token()
        request.session[CSRF_SESSION_KEY] = token
    return token


def rotate_csrf_token(request: Request) -> str:
    """ログイン成功などの境界でCSRFトークンを再発行する。"""
    token = _new_csrf_token()
    request.session[CSRF_SESSION_KEY] = token
    return token


def verify_csrf_token(
    request: Request,
    csrf_token: Annotated[str | None, Form(alias=CSRF_FORM_FIELD)] = None,
) -> None:
    """フォームから送られたCSRFトークンをセッション内の値と照合する。"""
    session_token = request.session.get(CSRF_SESSION_KEY)
    if (
        not isinstance(session_token, str)
        or not isinstance(csrf_token, str)
        or not secrets.compare_digest(session_token, csrf_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )


class CsrfTokenMiddleware(BaseHTTPMiddleware):
    """GET時にCSRFトークンを用意して、どのHTML入口からでもformを描画できるようにする。"""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method == "GET" and not request.url.path.startswith(
            CSRF_EXCLUDED_PATH_PREFIXES
        ):
            ensure_csrf_token(request)
        return await call_next(request)


def _new_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)
