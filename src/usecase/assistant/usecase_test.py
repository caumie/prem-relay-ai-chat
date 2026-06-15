from pathlib import Path

import pytest

from ...service.password import hash_password
from ...infrastructure import AuthRepository, Database
from ...models import AssistantGenerationConfig, ConnectionProvider, User, UserInputError
from ..admin_base_assistant import AdminBaseAssistantUsecaseContext
from ..admin_base_assistant.create_base_assistant import create_base_assistant
from . import AssistantUsecaseContext
from . import (
    AssistantUsecaseError,
    create_user_assistant,
    delete_user_assistant,
    list_available_assistants,
    list_manageable_user_assistants,
    resolve_runtime_assistant,
    update_user_assistant,
)


def test_list_available_assistants_groups_owned_then_system_then_other_public(
    tmp_path: Path,
) -> None:
    # 観点: チャット候補では自分作成、システム公開、他人公開の順で分類されること。
    # 目的: selectのoptgroup表示がusecaseの表示モデルだけで決まる契約を固定する。
    context = _context(tmp_path)
    database = context.database
    admin = _create_user(database, "admin", is_admin=True)
    user = _create_user(database, "user")
    other = _create_user(database, "other")

    standard = create_base_assistant(
        context=_admin_base_context(context),
        actor=admin,
        name="Standard",
        description="shared",
        system_prompt="system",
        user_prompts=["base prefix"],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=20,
        allow_file_upload=False,
        generation_config={"temperature": 0.2},
    )
    other_public = create_user_assistant(
        context=context,
        actor=other,
        base_assistant_id=standard.id,
        name="Other Public",
        description="shared by other",
        user_prompts=["other prefix"],
        visibility="public",
    )
    private = create_user_assistant(
        context=context,
        actor=user,
        base_assistant_id=standard.id,
        name="Private",
        description="mine",
        user_prompts=["mine prefix"],
        visibility="private",
    )

    own_available = list_available_assistants(context=context, user_id=user.id)
    other_available = list_available_assistants(context=context, user_id=other.id)

    assert [item.id for item in own_available] == [
        private.id,
        standard.id,
        other_public.id,
    ]
    assert [item.category for item in own_available] == [
        "owned",
        "system_public",
        "other_public",
    ]
    assert [item.description for item in own_available] == [
        "mine",
        "shared",
        "shared by other",
    ]
    assert [item.id for item in other_available] == [other_public.id, standard.id]


def test_resolve_runtime_assistant_merges_provider_and_assistant_config(
    tmp_path: Path,
) -> None:
    # 観点: 接続Providerとアシスタント設定が実行時Assistantへ合成されること。
    # 目的: DBに秘密情報を持たず、実行時だけ接続設定を解決する。
    context = _context(tmp_path, default_options={"temperature": 0.1})
    database = context.database
    user = _create_user(database, "user")
    admin = _create_user(database, "admin", is_admin=True)
    base = create_base_assistant(
        context=_admin_base_context(context),
        actor=admin,
        name="Base",
        description="shared",
        system_prompt="system",
        user_prompts=["base prefix"],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=20,
        allow_file_upload=True,
        generation_config={"reasoning_effort": "medium"},
    )
    created = create_user_assistant(
        context=context,
        actor=user,
        base_assistant_id=base.id,
        name="My Assistant",
        description="mine",
        user_prompts=["user prefix"],
        visibility="private",
    )

    runtime = resolve_runtime_assistant(
        context=context,
        user_id=user.id,
        assistant_id=created.id,
    )

    assert runtime.id == created.id
    assert runtime.api_mode == "responses"
    assert runtime.base_url == "https://api.openai.com/v1"
    assert runtime.system_prompt == "system"
    assert runtime.user_prompts == ["base prefix", "user prefix"]
    assert runtime.config == {
        "temperature": 0.1,
        "api_key": "secret",
        "model": "gpt-5",
        "allow_file_upload": True,
        "allowed_file_extensions": ["jpg", "jpeg", "png"],
        "reasoning_effort": "medium",
    }


def test_create_base_assistant_rejects_model_outside_provider_allowed_models(
    tmp_path: Path,
) -> None:
    # 観点: Providerが許可したモデル以外ではアシスタントを保存できないこと。
    # 目的: 編集画面の選択肢だけでなくusecase境界でもモデル制約を守る。
    context = _context(tmp_path)
    database = context.database

    with pytest.raises(UserInputError):
        create_base_assistant(
            context=_admin_base_context(context),
            actor=_create_user(database, "admin", is_admin=True),
            name="Bad Model",
            description="",
            system_prompt="",
            user_prompts=[],
            connection_provider_id="openai",
            model="other-model",
            max_history_messages=20,
            allow_file_upload=False,
            generation_config={},
        )


def test_create_user_assistant_requires_base_assistant(tmp_path: Path) -> None:
    # 観点: UserAssistantは元になるBaseAssistantなしでは保存できないこと。
    # 目的: UIを迂回した入力でも実行不能なMy Assistantを作らない。
    context = _context(tmp_path)
    database = context.database
    user = _create_user(database, "user")

    with pytest.raises(UserInputError, match="base assistant is required"):
        create_user_assistant(
            context=context,
            actor=user,
            base_assistant_id=None,
            name="No Base",
            description="",
            user_prompts=["friendly"],
            visibility="private",
        )


def test_create_user_assistant_assigns_owner_and_visibility(tmp_path: Path) -> None:
    # 観点: UserAssistant作成ユースケースが所有者と公開範囲を保存すること。
    # 目的: ユーザー画面が所有者決定や整形を持たずに作成処理を委譲できるようにする。
    context = _context(tmp_path)
    database = context.database
    owner = _create_user(database, "owner")
    admin = _create_user(database, "admin", is_admin=True)
    base = create_base_assistant(
        context=_admin_base_context(context),
        actor=admin,
        name="Base",
        description="shared",
        system_prompt="system",
        user_prompts=["base prefix"],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=20,
        allow_file_upload=False,
        generation_config={},
    )

    created = create_user_assistant(
        context=context,
        actor=owner,
        base_assistant_id=base.id,
        name="  Personal  ",
        description=" 個人用 ",
        user_prompts=[" friendly ", ""],
        visibility="public",
    )

    assert created.owner_user_id == owner.id
    assert created.name == "Personal"
    assert created.description == "個人用"
    assert created.user_prompts == ["friendly"]
    assert created.visibility == "public"


def test_update_user_assistant_rejects_non_owner_non_admin(tmp_path: Path) -> None:
    # 観点: 他人のマイアシスタントは管理者または所有者だけが編集できること。
    # 目的: Web編集導入後もアシスタント所有境界を崩さない。
    context = _context(tmp_path)
    database = context.database
    owner = _create_user(database, "owner")
    other = _create_user(database, "other")
    admin = _create_user(database, "admin", is_admin=True)
    base = create_base_assistant(
        context=_admin_base_context(context),
        actor=admin,
        name="Base",
        description="base",
        system_prompt="system",
        user_prompts=[],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=20,
        allow_file_upload=False,
        generation_config={},
    )
    created = create_user_assistant(
        context=context,
        actor=owner,
        base_assistant_id=base.id,
        name="My Assistant",
        description="mine",
        user_prompts=["prefix"],
        visibility="private",
    )

    with pytest.raises(AssistantUsecaseError):
        update_user_assistant(
            context=context,
            actor=other,
            user_assistant_id=created.id,
            base_assistant_id=base.id,
            name="Changed",
            description="mine",
            user_prompts=["prefix"],
            visibility="private",
        )


def test_update_user_assistant_rewrites_fields_for_owner(tmp_path: Path) -> None:
    # 観点: UserAssistant更新ユースケースが所有者による編集内容を保存すること。
    # 目的: ユーザー画面が更新差分の整形を持たずに更新処理を委譲できるようにする。
    context = _context(tmp_path)
    database = context.database
    owner = _create_user(database, "owner")
    admin = _create_user(database, "admin", is_admin=True)
    base = create_base_assistant(
        context=_admin_base_context(context),
        actor=admin,
        name="Base",
        description="base",
        system_prompt="system",
        user_prompts=[],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=20,
        allow_file_upload=False,
        generation_config={},
    )
    created = create_user_assistant(
        context=context,
        actor=owner,
        base_assistant_id=base.id,
        name="My Assistant",
        description="mine",
        user_prompts=["prefix"],
        visibility="private",
    )

    updated = update_user_assistant(
        context=context,
        actor=owner,
        user_assistant_id=created.id,
        base_assistant_id=base.id,
        name="  Personal Updated  ",
        description=" 更新済み ",
        user_prompts=[" focused ", ""],
        visibility="public",
    )

    assert updated.name == "Personal Updated"
    assert updated.description == "更新済み"
    assert updated.user_prompts == ["focused"]
    assert updated.visibility == "public"


def test_delete_user_assistant_hides_deleted_assistant_from_listing(
    tmp_path: Path,
) -> None:
    # 観点: UserAssistant削除ユースケースが一覧から対象assistantを除外すること。
    # 目的: ユーザー画面が削除後の表示除外を永続化詳細なしでusecaseへ委譲できるようにする。
    context = _context(tmp_path)
    database = context.database
    owner = _create_user(database, "owner")
    admin = _create_user(database, "admin", is_admin=True)
    base = create_base_assistant(
        context=_admin_base_context(context),
        actor=admin,
        name="Base",
        description="base",
        system_prompt="system",
        user_prompts=[],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=20,
        allow_file_upload=False,
        generation_config={},
    )
    created = create_user_assistant(
        context=context,
        actor=owner,
        base_assistant_id=base.id,
        name="My Assistant",
        description="mine",
        user_prompts=["prefix"],
        visibility="private",
    )

    deleted = delete_user_assistant(
        context=context, actor=owner, user_assistant_id=created.id
    )
    listed = list_manageable_user_assistants(owner, context=context)

    assert deleted is True
    assert [assistant.id for assistant in listed] == []


def _context(
    tmp_path: Path,
    *,
    default_options: AssistantGenerationConfig | None = None,
) -> AssistantUsecaseContext:
    """assistant ユースケース用のcontextを初期化して返す。"""
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    return AssistantUsecaseContext(
        database=database,
        load_connection_providers=lambda: [
            _provider("openai", default_options=default_options or {})
        ],
    )


def _admin_base_context(
    context: AssistantUsecaseContext,
) -> AdminBaseAssistantUsecaseContext:
    """assistantテスト用contextからbase assistant管理に必要な依存だけを返す。"""
    return AdminBaseAssistantUsecaseContext(
        database=context.database,
        load_connection_providers=context.load_connection_providers,
    )


def _create_user(
    database: Database, login_name: str, *, is_admin: bool = False
) -> User:
    with database.connect() as conn:
        user = AuthRepository(conn).create(
            login_name=login_name,
            is_admin=is_admin,
            password_hash=hash_password("password", "pepper"),
        )
        conn.commit()
    return user


def _provider(
    provider_id: str, *, default_options: AssistantGenerationConfig | None = None
) -> ConnectionProvider:
    return ConnectionProvider(
        id=provider_id,
        name=provider_id,
        description="",
        api_mode="responses",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        allowed_models=["gpt-5", "gpt-5-mini"],
        default_options=default_options or {},
    )
