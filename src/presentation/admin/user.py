"""admin 向け User 管理画面の HTML router を担当する。"""

import sqlite3
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ...models import User
from ...usecase.admin_user.create_user import create_user
from ...usecase.admin_user.delete_user import delete_user
from ...usecase.admin_user.get_user import get_user
from ...usecase.admin_user.list_users import list_users
from ...usecase.admin_user.suspend_user import suspend_user
from ...usecase.admin_user.update_user import update_user
from ...usecase.context import UsecaseContext
from ..util.csrf import verify_csrf_token

router = APIRouter()
templates: Jinja2Templates | None = None
_current_admin: Callable[[Request], Awaitable[User]] | None = None
_shell_context: Callable[[Request, User], dict[str, object]] | None = None
_usecase_context: UsecaseContext | None = None


def configure_admin_user_routes(
    *,
    usecase_context: UsecaseContext,
    current_admin: Callable[[Request], Awaitable[User]],
    shell_context: Callable[[Request, User], dict[str, object]],
) -> None:
    global _current_admin, _shell_context, _usecase_context
    _usecase_context = usecase_context
    _current_admin = current_admin
    _shell_context = shell_context


async def _current_admin_dependency(request: Request) -> User:
    if _current_admin is None:
        raise RuntimeError("Admin user current_admin is not configured")
    return await _current_admin(request)


def _templates() -> Jinja2Templates:
    if templates is None:
        raise RuntimeError("Admin user templates are not configured")
    return templates


def _shell_page_context(request: Request, user: User) -> dict[str, object]:
    if _shell_context is None:
        raise RuntimeError("Admin user shell_context is not configured")
    return _shell_context(request, user)


def _context() -> UsecaseContext:
    """admin user routerで利用するusecase contextを返す。"""
    if _usecase_context is None:
        raise RuntimeError("Admin user usecase context is not configured")
    return _usecase_context


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin: User = Depends(_current_admin_dependency),
) -> HTMLResponse:
    return _templates().TemplateResponse(
        request,
        "admin_users.html",
        {
            **_shell_page_context(request, admin),
            "users": list_users(_context()),
        },
    )


@router.post("/admin/users")
async def create_admin_user(
    _: None = Depends(verify_csrf_token),
    __: User = Depends(_current_admin_dependency),
    login_name: str = Form(...),
    password: str = Form(...),
    is_admin: str | None = Form(None),
) -> Response:
    if not login_name.strip() or not password:
        raise HTTPException(400, "login_name and password are required")
    create_user(
        _context(),
        login_name=login_name,
        password=password,
        is_admin=is_admin == "on",
    )
    return RedirectResponse("/admin/users", 303)


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_admin_user(
    request: Request,
    user_id: int,
    admin: User = Depends(_current_admin_dependency),
) -> HTMLResponse:
    user = get_user(_context(), user_id)
    if user is None:
        raise HTTPException(404)
    return _templates().TemplateResponse(
        request,
        "admin_user_form.html",
        {
            **_shell_page_context(request, admin),
            "editing_user": user,
        },
    )


@router.post("/admin/users/{user_id}/edit")
async def update_admin_user(
    user_id: int,
    _: None = Depends(verify_csrf_token),
    __: User = Depends(_current_admin_dependency),
    login_name: str = Form(...),
    password: str = Form(""),
    is_admin: str | None = Form(None),
) -> Response:
    if not login_name.strip():
        raise HTTPException(400, "login_name is required")
    try:
        update_user(
            _context(),
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
    admin: User = Depends(_current_admin_dependency),
) -> Response:
    if user_id == admin.id:
        raise HTTPException(400, "cannot suspend current admin")
    if not suspend_user(_context(), user_id=user_id):
        raise HTTPException(404)
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/users/{user_id}/delete")
async def delete_admin_user(
    user_id: int,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(_current_admin_dependency),
) -> Response:
    if user_id == admin.id:
        raise HTTPException(400, "cannot delete current admin")
    try:
        deleted = delete_user(_context(), user_id=user_id)
    except OSError as exc:
        raise HTTPException(500, "failed to delete attachment") from exc
    if not deleted:
        raise HTTPException(404)
    return RedirectResponse("/admin/users", 303)
