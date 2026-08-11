"""ユーザー向け assistant 管理画面の HTML router を担当する。"""

import logging
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

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
from .context import current_user, presentation_templates, shell_context
from .util.form import form_string_list, optional_form_string, required_form_string
from .util.csrf import verify_csrf_token


logger = logging.getLogger(__name__)
router = APIRouter()


class UserAssistantFormPayload(TypedDict):
    """UserAssistantフォームからusecaseへ渡す値を表す。"""

    base_assistant_id: str | None
    name: str
    description: str
    user_prompts: list[str]
    visibility: AssistantVisibility

@router.get("/assistants", response_class=HTMLResponse)
async def user_assistants(
    request: Request,
    user: User = Depends(current_user),
) -> HTMLResponse:
    """現在ユーザーが管理できるマイアシスタント一覧を表示する。"""
    return presentation_templates().TemplateResponse(
        request,
        "user_assistant_index.html",
        {
            **shell_context(request, user),
            "assistants": list_manageable_user_assistants(user),
            "base_assistant_names": {
                assistant.id: assistant.name
                for assistant in list_selectable_base_assistants()
            },
        },
    )


@router.get("/assistants/new", response_class=HTMLResponse)
async def user_assistant_new(
    request: Request,
    user: User = Depends(current_user),
) -> HTMLResponse:
    """現在ユーザー向けマイアシスタント作成フォームを表示する。"""
    return presentation_templates().TemplateResponse(
        request,
        "user_assistant_form.html",
        {
            **shell_context(request, user),
            **_user_assistant_form_context(
                base_assistants=list_selectable_base_assistants(),
                assistant=None,
            ),
        },
    )


@router.post("/assistants/new")
async def user_assistant_create(
    request: Request,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(current_user),
) -> Response:
    """現在ユーザー向けマイアシスタント作成フォームを処理する。"""
    try:
        assistant = create_user_assistant(
            actor=user,
            **await _user_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info(
        "audit.user_assistant.created actor_user_id=%s target_user_id=%s resource_id=%s result=success",
        user.id,
        user.id,
        assistant.id,
    )
    return RedirectResponse("/assistants", 303)


@router.get("/assistants/{assistant_id}/edit", response_class=HTMLResponse)
async def user_assistant_edit(
    request: Request,
    assistant_id: str,
    user: User = Depends(current_user),
) -> HTMLResponse:
    """現在ユーザー向けマイアシスタント編集フォームを表示する。"""
    try:
        assistant = get_manageable_user_assistant(
            actor=user,
            user_assistant_id=assistant_id,
        )
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return presentation_templates().TemplateResponse(
        request,
        "user_assistant_form.html",
        {
            **shell_context(request, user),
            **_user_assistant_form_context(
                base_assistants=list_selectable_base_assistants(),
                assistant=assistant,
            ),
        },
    )


@router.post("/assistants/{assistant_id}/edit")
async def user_assistant_update(
    request: Request,
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(current_user),
) -> Response:
    """現在ユーザー向けマイアシスタント編集フォームを処理する。"""
    try:
        assistant = update_user_assistant(
            actor=user,
            user_assistant_id=assistant_id,
            **await _user_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    logger.info(
        "audit.user_assistant.updated actor_user_id=%s target_user_id=%s resource_id=%s result=success",
        user.id,
        user.id,
        assistant.id,
    )
    return RedirectResponse("/assistants", 303)


@router.post("/assistants/{assistant_id}/delete")
async def user_assistant_delete(
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(current_user),
) -> Response:
    """現在ユーザー向けマイアシスタント削除を処理する。"""
    try:
        deleted = delete_user_assistant(
            actor=user,
            user_assistant_id=assistant_id,
        )
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    if deleted:
        logger.info(
            "audit.user_assistant.deleted actor_user_id=%s target_user_id=%s resource_id=%s result=success",
            user.id,
            user.id,
            assistant_id,
        )
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
        "base_assistant_id": required_form_string(
            form.get("base_assistant_id"),
            "base_assistant_id",
        ),
        "name": required_form_string(form.get("name"), "name"),
        "description": optional_form_string(form.get("description")),
        "user_prompts": form_string_list(form.getlist("user_prompts")),
        "visibility": _visibility_value(form.get("visibility", "private")),
    }


def _initial_user_prompts(user_prompts: list[str]) -> list[str]:
    """フォーム初期表示用のユーザープロンプト欄を返す。"""
    return user_prompts if user_prompts else [""]



def _visibility_value(value: object) -> AssistantVisibility:
    """フォーム値を assistant visibility へ正規化する。"""
    if value == "public":
        return "public"
    return "private"
