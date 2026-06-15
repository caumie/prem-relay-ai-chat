"""実行時 assistant 解決ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository, UserAssistantRepository
from ...models import ResolvedAssistant, UserInputError
from ._support import resolve_base
from . import AssistantUsecaseContext, assistant_usecase_context


def resolve_runtime_assistant(
    *,
    user_id: int,
    assistant_id: str,
    context: AssistantUsecaseContext | None = None,
) -> ResolvedAssistant:
    """利用者が選んだ assistant を接続先解決済みの実行形へ変換する。

    Args:
        user_id: 利用者 ID。
        assistant_id: 実行する BaseAssistant または UserAssistant ID。

    Returns:
        Provider の接続設定を合成した実行用 Assistant。
    """
    ctx = context if context is not None else assistant_usecase_context()
    with ctx.database.connect() as conn:
        base_repo = BaseAssistantRepository(conn)
        user_repo = UserAssistantRepository(conn)
        base = base_repo.get(assistant_id)
        if base is not None:
            return resolve_base(
                providers=ctx.load_connection_providers(),
                base=base,
            )
        user_assistant = user_repo.get(assistant_id)
        if user_assistant is None or (
            user_assistant.visibility != "public"
            and user_assistant.owner_user_id != user_id
        ):
            raise UserInputError("assistant is not available to this user")
        if user_assistant.base_assistant_id is None:
            raise UserInputError("base assistant is not assigned")
        base = base_repo.get(user_assistant.base_assistant_id)
        if base is None:
            raise UserInputError("base assistant is not assigned")
        return resolve_base(
            providers=ctx.load_connection_providers(),
            base=base,
            user_assistant=user_assistant,
        )
