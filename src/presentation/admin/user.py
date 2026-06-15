"""admin 向け User 管理画面の HTML router を担当する。"""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ...models import User
from ...usecase.admin_user import create_user, delete_user, get_user, list_users, suspend_user, update_user
from ..context import current_admin, presentation_templates, shell_context
from ..util.csrf import verify_csrf_token

router = APIRouter()


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
    __: User = Depends(current_admin),
    login_name: str = Form(...),
    password: str = Form(...),
    is_admin: str | None = Form(None),
) -> Response:
    if not login_name.strip() or not password:
        raise HTTPException(400, "login_name and password are required")
    create_user(
        login_name=login_name,
        password=password,
        is_admin=is_admin == "on",
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
    __: User = Depends(current_admin),
    login_name: str = Form(...),
    password: str = Form(""),
    is_admin: str | None = Form(None),
) -> Response:
    if not login_name.strip():
        raise HTTPException(400, "login_name is required")
    try:
        update_user(
            user_id=user_id,
            login_name=login_name,
            password=password,
            is_admin=is_admin == "on",
        )
    except RuntimeError as exc:
        raise HTTPException(404, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, "login_name must be unique") from exc
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/users/{user_id}/suspend")
async def suspend_admin_user(
    user_id: int,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    if user_id == admin.id:
        raise HTTPException(400, "cannot suspend current admin")
    if not suspend_user(user_id=user_id):
        raise HTTPException(404)
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/users/{user_id}/delete")
async def delete_admin_user(
    user_id: int,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    if user_id == admin.id:
        raise HTTPException(400, "cannot delete current admin")
    try:
        deleted = delete_user(user_id=user_id)
    except OSError as exc:
        raise HTTPException(500, "failed to delete attachment") from exc
    if not deleted:
        raise HTTPException(404)
    return RedirectResponse("/admin/users", 303)
