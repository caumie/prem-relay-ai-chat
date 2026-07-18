"""
認証に関するHTML router
ログインフォーム、ログイン処理、ログアウト、トップページへのリダイレクト
"""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..usecase.auth import challenge
from .context import presentation_templates
from .util.csrf import ensure_csrf_token, rotate_csrf_token, verify_csrf_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    """ログインフォームを表示する"""
    logger.info("login request received")
    return presentation_templates().TemplateResponse(
        request,
        "login.html",
        dict(error=False, login_name="", csrf_token=ensure_csrf_token(request)),
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    _: None = Depends(verify_csrf_token),
    login_name: str = Form(...),
    password: str = Form(...),
) -> Response:
    """ログインフォームの入力でセッションを開始する。"""
    logger.info("login submit received")
    # TODO: 接続元とログイン名を基準に試行回数を制限し、同期的な
    # パスワード導出処理はevent loopを塞がない実行境界へ移す。
    user = challenge(login_name=login_name, password=password)

    if not user:
        logger.warning("auth.failed")
        return presentation_templates().TemplateResponse(
            request,
            "login.html",
            dict(
                error=True,  # エラーメッセージなどUIの情報はテンプレート側で判断する
                login_name=login_name,
                csrf_token=ensure_csrf_token(request),
            ),
            status_code=401,
        )

    request.session["user_id"] = user.id
    rotate_csrf_token(request)
    logger.info("auth.success user_id=%s", user.id)
    return RedirectResponse("/chat", 303)


@router.post("/logout")
async def logout(
    request: Request,
    _: None = Depends(verify_csrf_token),
) -> Response:
    """セッションを破棄してログアウトする。"""
    logger.info("logout user_id=%s", request.session.get("user_id"))
    request.session.clear()
    return RedirectResponse("/login", 303)
