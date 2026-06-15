"""admin 向け BaseAssistant 管理画面の HTML router を担当する。"""

from collections.abc import Sequence
from json import JSONDecodeError, dumps, loads
import re
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ...models import (
    AssistantGenerationConfig,
    BaseAssistant,
    ConnectionProvider,
    JsonValue,
    User,
    UserInputError,
    default_assistant_file_extensions,
    is_assistant_config_value,
)
from ...usecase.admin_base_assistant.create_base_assistant import create_base_assistant
from ...usecase.admin_base_assistant.delete_base_assistant import delete_base_assistant
from ...usecase.admin_base_assistant.get_base_assistant import get_base_assistant
from ...usecase.admin_base_assistant.list_base_assistants import list_base_assistants
from ...usecase.admin_base_assistant.list_connection_providers import (
    list_connection_providers,
)
from ...usecase.admin_base_assistant.update_base_assistant import update_base_assistant
from ...usecase.assistant import AssistantUsecaseError
from ..context import current_admin, presentation_templates, shell_context
from ..util.csrf import verify_csrf_token

router = APIRouter()


class BaseAssistantFormPayload(TypedDict):
    """BaseAssistantフォームからusecaseへ渡す値を表す。"""

    name: str
    description: str
    system_prompt: str
    user_prompts: list[str]
    connection_provider_id: str
    model: str
    max_history_messages: int
    allow_file_upload: bool
    allowed_file_extensions: list[str]
    generation_config: AssistantGenerationConfig

@router.get("/admin/base-assistants", response_class=HTMLResponse)
async def admin_base_assistants(
    request: Request,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    return presentation_templates().TemplateResponse(
        request,
        "base_assistant_index.html",
        {
            **shell_context(request, admin),
            "assistants": list_base_assistants(),
            "connection_provider_names": {
                provider.id: provider.name
                for provider in list_connection_providers()
            },
        },
    )


@router.get("/admin/base-assistants/new", response_class=HTMLResponse)
async def admin_base_assistant_new(
    request: Request,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    return presentation_templates().TemplateResponse(
        request,
        "base_assistant_form.html",
        {
            **shell_context(request, admin),
            **_base_assistant_form_context(
                providers=list_connection_providers(),
                assistant=None,
            ),
        },
    )


@router.post("/admin/base-assistants/new")
async def admin_base_assistant_create(
    request: Request,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        create_base_assistant(
            actor=admin,
            **await _base_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin/base-assistants", 303)


@router.get("/admin/base-assistants/{assistant_id}/edit", response_class=HTMLResponse)
async def admin_base_assistant_edit(
    request: Request,
    assistant_id: str,
    admin: User = Depends(current_admin),
) -> HTMLResponse:
    try:
        assistant = get_base_assistant(base_assistant_id=assistant_id)
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return presentation_templates().TemplateResponse(
        request,
        "base_assistant_form.html",
        {
            **shell_context(request, admin),
            **_base_assistant_form_context(
                providers=list_connection_providers(),
                assistant=assistant,
            ),
        },
    )


@router.post("/admin/base-assistants/{assistant_id}/edit")
async def admin_base_assistant_update(
    request: Request,
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        update_base_assistant(
            actor=admin,
            base_assistant_id=assistant_id,
            **await _base_assistant_form_payload(request),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse("/admin/base-assistants", 303)


@router.post("/admin/base-assistants/{assistant_id}/delete")
async def admin_base_assistant_delete(
    assistant_id: str,
    _: None = Depends(verify_csrf_token),
    admin: User = Depends(current_admin),
) -> Response:
    try:
        delete_base_assistant(actor=admin, base_assistant_id=assistant_id)
    except AssistantUsecaseError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse("/admin/base-assistants", 303)


def _base_assistant_form_context(
    *,
    providers: list[ConnectionProvider],
    assistant: BaseAssistant | None,
) -> dict[str, object]:
    provider_models = {provider.id: provider.allowed_models for provider in providers}
    return {
        "providers": providers,
        "provider_models_json": dumps(provider_models, ensure_ascii=False),
        "assistant": assistant,
        "user_prompts": assistant.user_prompts if assistant and assistant.user_prompts else [""],
        "allowed_file_extensions_text": ", ".join(
            assistant.allowed_file_extensions
            if assistant is not None
            else default_assistant_file_extensions()
        ),
        "generation_config_json": dumps(
            assistant.generation_config if assistant is not None else {},
            ensure_ascii=False,
            indent=2,
        ),
    }


async def _base_assistant_form_payload(request: Request) -> BaseAssistantFormPayload:
    form = await request.form()
    max_history_raw = form.get("max_history_messages", "40")
    if not isinstance(max_history_raw, str) or not max_history_raw.isdigit():
        raise UserInputError("max_history_messages must be a positive integer")
    return {
        "name": _required_str(form.get("name"), "name"),
        "description": _optional_str(form.get("description")),
        "system_prompt": _optional_str(form.get("system_prompt")),
        "user_prompts": _form_string_list(form.getlist("user_prompts")),
        "connection_provider_id": _required_str(
            form.get("connection_provider_id"),
            "connection_provider_id",
        ),
        "model": _required_str(form.get("model"), "model"),
        "max_history_messages": int(max_history_raw),
        "allow_file_upload": form.get("allow_file_upload") == "on",
        "allowed_file_extensions": _extension_string_list(
            _optional_str(form.get("allowed_file_extensions"))
        ),
        "generation_config": _generation_config_from_json(
            _optional_str(form.get("generation_config_json"))
        ),
    }


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UserInputError(f"{field_name} is required")
    return value.strip()


def _optional_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _form_string_list(values: Sequence[object]) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def _extension_string_list(raw_value: str) -> list[str]:
    """フォームの拡張子テキストをusecaseへ渡すリストへ分解する。

    Args:
        raw_value: カンマ、空白、改行で区切られた拡張子入力。

    Returns:
        空欄を除いた拡張子文字列一覧。
    """
    return [value for value in re.split(r"[\s,]+", raw_value) if value]


def _generation_config_from_json(raw_json: str) -> AssistantGenerationConfig:
    if not raw_json.strip():
        return {}
    try:
        decoded: JsonValue = loads(raw_json)
    except JSONDecodeError as exc:
        raise UserInputError("generation_config_json must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise UserInputError("generation_config_json must be a JSON object")
    config: AssistantGenerationConfig = {}
    for raw_key, raw_value in decoded.items():
        if is_assistant_config_value(raw_value):
            config[raw_key] = raw_value
        else:
            raise UserInputError("generation_config_json values must be JSON values")
    return config
