"""ユーザー向け assistant 管理画面の HTML router を担当する。"""

from collections.abc import Awaitable, Callable
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData

from ..models import (
    AssistantVisibility,
    BaseAssistant,
    User,
    UserAssistant,
    UserInputError,
)
from ..usecase.assistant import (
    AssistantUsecaseError,
    create_user_assistant,
    delete_user_assistant,
    get_manageable_user_assistant,
    list_manageable_user_assistants,
    update_user_assistant,
)
from ..usecase.assistant.list_selectable_base_assistants import (
    list_selectable_base_assistants,
)
from ..usecase.context import UsecaseContext
from .util.csrf import verify_csrf_token


router = APIRouter()
templates: Jinja2Templates | None = None
_current_user: Callable[[Request], Awaitable[User]] | None = None
_shell_context: Callable[[Request, User], dict[str, object]] | None = None
_usecase_context: UsecaseContext | None = None


class UserAssistantFormPayload(TypedDict):
    """UserAssistantフォームからusecaseへ渡す値を表す。"""

    base_assistant_id: str | None
    name: str
    description: str
    user_prompts: list[str]
    visibility: AssistantVisibility


def configure_assistant_routes(
    *,
    usecase_context: UsecaseContext,
    current_user: Callable[[Request], Awaitable[User]],
    shell_context: Callable[[Request, User], dict[str, object]],
) -> None:
    """assistant router で使う依存関係を設定する。

    Args:
        current_user: 現在ユーザーを返す依存関係。
        shell_context: 共通テンプレート context を作る関数。

    Returns:
        None。
    """
    global _current_user, _shell_context, _usecase_context
    _usecase_context = usecase_context
    _current_user = current_user
    _shell_context = shell_context


async def _current_user_dependency(request: Request) -> User:
    """assistant router 用の現在ユーザー依存関係を返す。"""
    if _current_user is None:
        raise RuntimeError("Assistant current_user dependency is not configured")
    return await _current_user(request)


def _templates() -> Jinja2Templates:
    """assistant router で利用するテンプレート設定を返す。"""
    if templates is None:
        raise RuntimeError("Assistant templates are not configured")
    return templates


def _shell_page_context(
    request: Request,
    user: User,
) -> dict[str, object]:
    """assistant 画面共通の shell context を返す。"""
    if _shell_context is None:
        raise RuntimeError("Assistant shell_context is not configured")
    return _shell_context(request, user)


def _context() -> UsecaseContext:
    """assistant routerで利用するusecase contextを返す。"""
    if _usecase_context is None:
        raise RuntimeError("Assistant usecase context is not configured")
    return _usecase_context


@router.get("/assistants", response_class=HTMLResponse)
async def user_assistants(
    request: Request,
    user: User = Depends(_current_user_dependency),
) -> HTMLResponse:
    """現在ユーザーが管理できるマイアシスタント一覧を表示する。"""
    return _templates().TemplateResponse(
        request,
        "user_assistant_index.html",
        {
            **_shell_page_context(request, user),
            "assistants": list_manageable_user_assistants(_context(), user),
            "base_assistant_names": {
                assistant.id: assistant.name
                for assistant in list_selectable_base_assistants(_context())
            },
        },
    )


@router.get("/assistants/new", response_class=HTMLResponse)
async def user_assistant_new(
    request: Request,
    user: User = Depends(_current_user_dependency),
) -> HTMLResponse:
    """現在ユーザー向けマイアシスタント作成フォームを表示する。"""
    return _templates().TemplateResponse(
        request,
        "user_assistant_form.html",
        {
            **_shell_page_context(request, user),
            **_user_assistant_form_context(
                base_assistants=list_selectable_base_assistants(_context()),
                assistant=None,
            ),
        },
    )


@router.post("/assistants/new")
async def user_assistant_create(
    request: Request,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
) -> Response:
    """現在ユーザー向けマイアシスタント作成フォームを処理する。"""
    try:
        create_user_assistant(
            _context(),
            actor=user,
            **await _user_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/assistants", 303)


@router.get("/assistants/{assistant_id}/edit", response_class=HTMLResponse)
async def user_assistant_edit(
    request: Request,
    assistant_id: str,
    user: User = Depends(_current_user_dependency),
) -> HTMLResponse:
    """現在ユーザー向けマイアシスタント編集フォームを表示する。"""
    try:
        assistant = get_manageable_user_assistant(
            _context(),
            actor=user,
            user_assistant_id=assistant_id,
        )
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _templates().TemplateResponse(
        request,
        "user_assistant_form.html",
        {
            **_shell_page_context(request, user),
            **_user_assistant_form_context(
                base_assistants=list_selectable_base_assistants(_context()),
                assistant=assistant,
            ),
        },
    )


@router.post("/assistants/{assistant_id}/edit")
async def user_assistant_update(
    request: Request,
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
) -> Response:
    """現在ユーザー向けマイアシスタント編集フォームを処理する。"""
    try:
        update_user_assistant(
            _context(),
            actor=user,
            user_assistant_id=assistant_id,
            **await _user_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse("/assistants", 303)


@router.post("/assistants/{assistant_id}/delete")
async def user_assistant_delete(
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
) -> Response:
    """現在ユーザー向けマイアシスタント削除を処理する。"""
    try:
        delete_user_assistant(
            _context(),
            actor=user,
            user_assistant_id=assistant_id,
        )
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse("/assistants", 303)


def _user_assistant_form_context(
    *,
    base_assistants: list[BaseAssistant],
    assistant: UserAssistant | None,
) -> dict[str, object]:
    """UserAssistant 作成・編集フォームのテンプレート context を組み立てる。"""
    return {
        "assistant": assistant,
        "base_assistants": base_assistants,
        "user_prompts": _initial_user_prompts(
            assistant.user_prompts if assistant is not None else [],
        ),
    }


async def _user_assistant_form_payload(request: Request) -> UserAssistantFormPayload:
    """UserAssistant 作成・編集フォーム値を usecase へ渡す形へ変換する。"""
    form = await request.form()
    return {
        "base_assistant_id": _required_str(
            form.get("base_assistant_id"),
            "base_assistant_id",
        ),
        "name": _required_str(form.get("name"), "name"),
        "description": _optional_str(form.get("description")),
        "user_prompts": _form_string_list(form, "user_prompts"),
        "visibility": _visibility_value(form.get("visibility", "private")),
    }


def _initial_user_prompts(user_prompts: list[str]) -> list[str]:
    """フォーム初期表示用のユーザープロンプト欄を返す。"""
    return user_prompts if user_prompts else [""]


def _required_str(value: object, field_name: str) -> str:
    """必須文字列フォーム値を検証して返す。"""
    if not isinstance(value, str) or not value.strip():
        raise UserInputError(f"{field_name} is required")
    return value.strip()


def _optional_str(value: object) -> str:
    """任意文字列フォーム値を返す。"""
    return value.strip() if isinstance(value, str) else ""


def _form_string_list(form: FormData, field_name: str) -> list[str]:
    """複数行フォーム値から空欄を除いた文字列一覧を返す。"""
    values = form.getlist(field_name)
    return [
        value.strip() for value in values if isinstance(value, str) and value.strip()
    ]


def _visibility_value(value: object) -> AssistantVisibility:
    """フォーム値を assistant visibility へ正規化する。"""
    if value == "public":
        return "public"
    return "private"
