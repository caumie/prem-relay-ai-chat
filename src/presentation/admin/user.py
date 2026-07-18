"""admin 向け User 管理画面の HTML router を担当する。"""

import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ...models import User
from ...usecase.admin_user import (
    AdminUserError,
    AdminUserNotFoundError,
    AdminUserPermissionError,
    CannotModifyCurrentAdminError,
    LastActiveAdminError,
    create_user,
    delete_user,
    get_user,
    list_users,
    suspend_user,
    update_user,
)
from ..context import current_admin, presentation_templates, shell_context
from ..util.csrf import verify_csrf_token

logger = logging.getLogger(__name__)
router = APIRouter()


def _admin_user_http_exception(error: AdminUserError) -> HTTPException:
    """管理ユーザー業務例外をHTTP例外へ変換する。"""
    if isinstance(error, AdminUserNotFoundError):
        return HTTPException(404)
    if isinstance(error, LastActiveAdminError):
        return HTTPException(409, "cannot remove the last active admin")
    if isinstance(error, CannotModifyCurrentAdminError):
        return HTTPException(400, "cannot modify current admin")
    if isinstance(error, AdminUserPermissionError):
        return HTTPException(403)
    return HTTPException(400, "invalid admin user operation")


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    return presentation_templates().TemplateResponse(
        request,
        "admin_users.html",
        {
            **shell_context(request, admin),
            "users": list_users(),
        },
    )


@router.post("/admin/users")
async def create_admin_user(
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
    login_name: str = Form(...),
    password: str = Form(...),
    is_admin: str | None = Form(None),
) -> Response:
    if not login_name.strip() or not password:
        raise HTTPException(400, "login_name and password are required")
    user = create_user(
        login_name=login_name,
        password=password,
        is_admin=is_admin == "on",
    )
    logger.info(
        "audit.user.created actor_user_id=%s target_user_id=%s result=success",
        admin.id,
        user.id,
    )
    return RedirectResponse("/admin/users", 303)


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_admin_user(
    request: Request,
    user_id: int,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    user = get_user(user_id=user_id)
    if user is None:
        raise HTTPException(404)
    return presentation_templates().TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **shell_context(request, admin),
            "editing_user": user,
        },
    )


@router.post("/admin/users/{user_id}/edit")
async def update_admin_user(
    user_id: int,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
    login_name: str = Form(...),
    password: str = Form(""),
    is_admin: str | None = Form(None),
) -> Response:
    if not login_name.strip():
        raise HTTPException(400, "login_name is required")
    try:
        user = update_user(
            user_id=user_id,
            login_name=login_name,
            password=password,
            is_admin=is_admin == "on",
            actor=admin,
        )
    except AdminUserError as exc:
        raise _admin_user_http_exception(exc) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, "login_name must be unique") from exc
    logger.info(
        "audit.user.updated actor_user_id=%s target_user_id=%s result=success",
        admin.id,
        user.id,
    )
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/users/{user_id}/suspend")
async def suspend_admin_user(
    user_id: int,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        suspend_user(user_id=user_id, actor=admin)
    except AdminUserError as exc:
        raise _admin_user_http_exception(exc) from exc
    logger.info(
        "audit.user.suspended actor_user_id=%s target_user_id=%s result=success",
        admin.id,
        user_id,
    )
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/users/{user_id}/delete")
async def delete_admin_user(
    user_id: int,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        delete_user(user_id=user_id, actor=admin)
    except OSError as exc:
        raise HTTPException(500, "failed to delete attachment") from exc
    except AdminUserError as exc:
        raise _admin_user_http_exception(exc) from exc
    logger.info(
        "audit.user.deleted actor_user_id=%s target_user_id=%s result=success",
        admin.id,
        user_id,
    )
    return RedirectResponse("/admin/users", 303)
