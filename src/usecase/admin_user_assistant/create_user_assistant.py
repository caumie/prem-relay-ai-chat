"""admin user assistant 作成ユースケースを担当する。"""

from uuid import uuid4

from ...infrastructure import BaseAssistantRepository, UserAssistantRepository
from ...models import AssistantVisibility, User, UserAssistant, UserInputError
from ..assistant.errors import AssistantUsecaseError
from ..context import UsecaseContext


def create_user_assistant(
    context: UsecaseContext,
    *,
    actor: User,
    base_assistant_id: str | None,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
) -> UserAssistant:
    """admin が所有する UserAssistant を作成する。

    Args:
        actor: 作成者である管理者。
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        description: 説明。
        user_prompts: 追加入力指示。
        visibility: 公開範囲。

    Returns:
        作成した UserAssistant。

    admin 管理画面の作成処理を user 向け usecase に依存せず独立して扱うため。
    """
    _require_admin(actor)
    _validate_fields(
        base_assistant_id=base_assistant_id,
        name=name,
        visibility=visibility,
    )
    with context.database.connect() as conn:
        base_repo = BaseAssistantRepository(conn)
        if base_assistant_id is None or base_repo.get(base_assistant_id) is None:
            raise UserInputError("base assistant is required")
        assistant = UserAssistantRepository(conn).save(
            UserAssistant(
                id=str(uuid4()),
                base_assistant_id=base_assistant_id,
                owner_user_id=actor.id,
                name=name.strip(),
                description=description.strip(),
                user_prompts=_clean_prompts(user_prompts),
                visibility=visibility,
            )
        )
        conn.commit()
        return assistant


def _require_admin(actor: User) -> None:
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")


def _clean_prompts(prompts: list[str]) -> list[str]:
    return [prompt.strip() for prompt in prompts if prompt.strip()]


def _validate_fields(
    *,
    base_assistant_id: str | None,
    name: str,
    visibility: AssistantVisibility,
) -> None:
    if base_assistant_id is None or not base_assistant_id.strip():
        raise UserInputError("base assistant is required")
    if not name.strip():
        raise UserInputError("name is required")
    if visibility not in ("private", "public"):
        raise UserInputError("visibility is required")
