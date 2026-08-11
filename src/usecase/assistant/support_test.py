"""Assistantユースケース共通補助の挙動を検証する。"""

import pytest

from src.models import ConnectionProvider, User

from ._support import (
    build_base_assistant,
    normalize_file_extensions_or_default,
    require_admin,
    validate_base_fields,
)
from .errors import AssistantUsecaseError


def test_assistant_support_normalizes_shared_input_rules() -> None:
    """BaseAssistant共通構築処理がpromptと拡張子を整形する。"""
    # 観点: 作成・更新から共通利用する構築処理が入力整形を一度だけ担うこと。
    # 目的: 同じ整形ロジックを複数のAssistantユースケースへ複製しない。
    assistant = build_base_assistant(
        assistant_id="base-1",
        name="  Base  ",
        description=" description ",
        system_prompt=" system ",
        user_prompts=[" one ", "", "two"],
        connection_provider_id="provider",
        model=" model ",
        max_history_messages=20,
        allow_file_upload=True,
        generation_config={},
        allowed_file_extensions=[".PNG", "png"],
    )

    assert assistant.name == "Base"
    assert assistant.user_prompts == ["one", "two"]
    assert assistant.allowed_file_extensions == ["png"]
    assert normalize_file_extensions_or_default([])


def test_assistant_support_reuses_admin_and_base_validation_rules() -> None:
    """共通のBaseAssistant入力検証と管理者判定が契約どおり動作する。"""
    # 観点: 共通検証が有効な入力を受け、一般ユーザーを管理者処理から拒否すること。
    # 目的: 作成・更新ユースケースに同じ認証・検証分岐を繰り返さない。
    provider = ConnectionProvider(
        id="provider",
        name="Provider",
        description="",
        api_mode="responses",
        base_url=None,
        api_key="",
        allowed_models=["model"],
        default_options={},
    )
    validate_base_fields(
        providers=[provider],
        connection_provider_id="provider",
        name="Base",
        model="model",
        max_history_messages=1,
    )

    with pytest.raises(AssistantUsecaseError, match="admin required"):
        require_admin(User(id=1, login_name="user", is_admin=False))

