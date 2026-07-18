"""
トップページの router
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.usecase.initial_setup.get_initial_setup_status import get_initial_setup_status

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    """トップページを表示する"""

    # 初期セットアップが完了していない場合は初期セットアップ画面へリダイレクトする
    initial_setup_status = get_initial_setup_status()
    if initial_setup_status.can_create_initial_admin:
        logger.info("index.redirect target=/setup/admin reason=initial_setup_pending")
        return RedirectResponse("/setup/admin", 303)

    # ユーザーがログインしているかどうかでリダイレクト先を変える
    user_id = request.session.get("user_id")
    if user_id:
        logger.info("index.redirect target=/chat reason=session_user_present user_id=%s", user_id)
        return RedirectResponse("/chat", 303)
    else:
        logger.info("index.redirect target=/login reason=no_session")
        return RedirectResponse("/login", 303)
