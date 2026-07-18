"""admin 向け UserAssistant 管理画面の HTML router を担当する。"""

import logging
from collections.abc import Sequence
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ...models import AssistantVisibility, BaseAssistant, User, UserAssistant, UserInputError
from ...usecase.admin_base_assistant.list_base_assistants import list_base_assistants
from ...usecase.admin_user import list_users
from ...usecase.admin_user_assistant.create_user_assistant import create_user_assistant
from ...usecase.admin_user_assistant.delete_user_assistant import delete_user_assistant
from ...usecase.admin_user_assistant.get_manageable_user_assistant import (
    get_manageable_user_assistant,
)
from ...usecase.admin_user_assistant.list_manageable_user_assistants import (
    list_manageable_user_assistants,
)
from ...usecase.admin_user_assistant.update_user_assistant import update_user_assistant
from ...usecase.assistant import AssistantUsecaseError
from ..context import current_admin, presentation_templates, shell_context
from ..util.csrf import verify_csrf_token


logger = logging.getLogger(__name__)
router = APIRouter()


class UserAssistantFormPayload(TypedDict):
    """UserAssistantフォームからusecaseへ渡す値を表す。"""

    base_assistant_id: str | None
    name: str
    description: str
    user_prompts: list[str]
    visibility: AssistantVisibility

@router.get("/admin/user-assistants", response_class=HTMLResponse)
async def admin_user_assistants(
    request: Request,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    base_names = {
        assistant.id: assistant.name for assistant in list_base_assistants()
    }
    return presentation_templates().TemplateResponse(
        request,
        "admin_user_assistant_index.html",
        {
            **shell_context(request, admin),
            "assistants": list_manageable_user_assistants(admin),
            "base_assistant_names": base_names,
            "assistant_owner_names": {
                user.id: user.login_name for user in list_users()
            },
        },
    )


@router.get("/admin/user-assistants/new", response_class=HTMLResponse)
async def admin_user_assistant_new(
    request: Request,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    return presentation_templates().TemplateResponse(
        request,
        "admin_user_assistant_form.html",
        {
            **shell_context(request, admin),
            **_user_assistant_form_context(
                base_assistants=list_base_assistants(),
                assistant=None,
            ),
        },
    )


@router.post("/admin/user-assistants/new")
async def admin_user_assistant_create(
    request: Request,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        assistant = create_user_assistant(
            actor=admin,
            **await _user_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info(
        "audit.admin_user_assistant.created actor_user_id=%s target_user_id=%s resource_id=%s result=success",
        admin.id,
        assistant.owner_user_id,
        assistant.id,
    )
    return RedirectResponse("/admin/user-assistants", 303)


@router.get("/admin/user-assistants/{assistant_id}/edit", response_class=HTMLResponse)
async def admin_user_assistant_edit(
    request: Request,
    assistant_id: str,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    try:
        assistant = get_manageable_user_assistant(
            actor=admin,
            user_assistant_id=assistant_id,
        )
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return presentation_templates().TemplateResponse(
        request,
        "admin_user_assistant_form.html",
        {
            **shell_context(request, admin),
            **_user_assistant_form_context(
                base_assistants=list_base_assistants(),
                assistant=assistant,
            ),
        },
    )


@router.post("/admin/user-assistants/{assistant_id}/edit")
async def admin_user_assistant_update(
    request: Request,
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        assistant = update_user_assistant(
            actor=admin,
            user_assistant_id=assistant_id,
            **await _user_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    logger.info(
        "audit.admin_user_assistant.updated actor_user_id=%s target_user_id=%s resource_id=%s result=success",
        admin.id,
        assistant.owner_user_id,
        assistant.id,
    )
    return RedirectResponse("/admin/user-assistants", 303)


@router.post("/admin/user-assistants/{assistant_id}/delete")
async def admin_user_assistant_delete(
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        assistant = get_manageable_user_assistant(
            actor=admin,
            user_assistant_id=assistant_id,
        )
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    deleted = delete_user_assistant(
        actor=admin,
        user_assistant_id=assistant_id,
    )
    if deleted:
        logger.info(
            "audit.admin_user_assistant.deleted actor_user_id=%s target_user_id=%s resource_id=%s result=success",
            admin.id,
            assistant.owner_user_id,
            assistant.id,
        )
    return RedirectResponse("/admin/user-assistants", 303)


def _user_assistant_form_context(
    *,
    base_assistants: list[BaseAssistant],
    assistant: UserAssistant | None,
) -> dict[str, object]:
    return {
        "assistant": assistant,
        "base_assistants": base_assistants,
        "user_prompts": assistant.user_prompts if assistant is not None else [""],
    }


async def _user_assistant_form_payload(request: Request) -> UserAssistantFormPayload:
    form = await request.form()
    return {
        "base_assistant_id": _required_str(form.get("base_assistant_id"), "base_assistant_id"),
        "name": _required_str(form.get("name"), "name"),
        "description": _optional_str(form.get("description")),
        "user_prompts": _form_string_list(form.getlist("user_prompts")),
        "visibility": _visibility_value(form.get("visibility", "private")),
    }


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UserInputError(f"{field_name} is required")
    return value.strip()


def _optional_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _form_string_list(values: Sequence[object]) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def _visibility_value(value: object) -> AssistantVisibility:
    if value == "public":
        return "public"
    return "private"
