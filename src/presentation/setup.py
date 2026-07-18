"""初回セットアップ画面のHTML routerを担当する。"""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..usecase.initial_setup import (
    InitialAdminAlreadyExistsError,
    create_initial_admin,
    get_initial_setup_status,
)
from .context import presentation_templates
from .util.csrf import ensure_csrf_token, verify_csrf_token

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/setup/admin", response_class=HTMLResponse)
async def initial_admin_setup_form(request: Request) -> Response:
    """初回管理者作成フォームを表示する。

    Args:
        request: HTML描画対象のFastAPI request。

    Returns:
        初回管理者作成フォーム、またはセットアップ済みならログイン画面へのredirect。

    管理者が存在しない環境だけに未ログインの管理者作成導線を開くため。
    """
    status = get_initial_setup_status()
    if not status.can_create_initial_admin:
        return RedirectResponse("/login", 303)
    return presentation_templates().TemplateResponse(
        request,
        "setup_admin.html",
        {
            "error": False,
            "login_name": "",
            "csrf_token": ensure_csrf_token(request),
        },
    )


@router.post("/setup/admin")
async def create_initial_admin_from_form(
    request: Request,
    _: None = Depends(verify_csrf_token),
    login_name: str = Form(...),
    password: str = Form(...),
) -> Response:
    """初回管理者作成フォームの入力で管理者を作成する。

    Args:
        request: フォーム送信元のFastAPI request。
        _: CSRF検証dependencyの結果。
        login_name: 作成する管理者ログイン名。
        password: 作成する管理者の平文パスワード。

    Returns:
        作成成功時はログイン画面へのredirect。入力不備時はフォーム再表示。

    routeはHTTPフォームと表示制御だけを扱い、作成可否や保存形式はusecaseへ委譲する。
    """
    if not login_name.strip() or not password:
        logger.warning(
            "audit.initial_admin.denied actor=initial_setup result=denied reason=invalid_input"
        )
        return presentation_templates().TemplateResponse(
            request,
            "setup_admin.html",
            {
                "error": True,
                "login_name": login_name,
                "csrf_token": ensure_csrf_token(request),
            },
            status_code=400,
        )
    try:
        user = create_initial_admin(
            login_name=login_name,
            password=password,
        )
    except InitialAdminAlreadyExistsError:
        logger.info(
            "audit.initial_admin.denied actor=initial_setup result=denied reason=already_exists"
        )
        return RedirectResponse("/login", 303)
    logger.info(
        "audit.initial_admin.created actor=initial_setup target_user_id=%s result=success",
        user.id,
    )
    return RedirectResponse("/login", 303)
