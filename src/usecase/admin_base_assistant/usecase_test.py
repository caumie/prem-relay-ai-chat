"""admin base assistant ユースケースの責務を検証する。"""

from pathlib import Path

from src.infrastructure import BaseAssistantRepository, Database
from src.models import ConnectionProvider
from src.models import User
from src.usecase.admin_base_assistant import AdminBaseAssistantUsecaseContext

from .create_base_assistant import create_base_assistant
from .delete_base_assistant import delete_base_assistant
from .update_base_assistant import update_base_assistant


def test_create_base_assistant_persists_trimmed_prompts_and_fields(
    tmp_path: Path,
) -> None:
    # 観点: base assistant作成ユースケースが入力整形と保存を担うこと。
    # 目的: 管理画面がprovider制約やprompt整形を知らずに作成処理を委譲できるようにする。
    context = _context(tmp_path)
    database = context.database

    created = create_base_assistant(
        context=context,
        actor=_admin(),
        name=" Ops ",
        description=" 運用用 ",
        system_prompt=" be helpful ",
        user_prompts=[" one ", " ", "two"],
        connection_provider_id="openai",
        model="gpt-5-mini",
        max_history_messages=20,
        allow_file_upload=True,
        allowed_file_extensions=["JPG", ".png", "jpg"],
        generation_config={"temperature": 0.2},
    )

    with database.connect() as conn:
        stored = BaseAssistantRepository(conn).get(created.id)

    assert stored is not None
    assert stored.name == "Ops"
    assert stored.description == "運用用"
    assert stored.system_prompt == "be helpful"
    assert stored.user_prompts == ["one", "two"]
    assert stored.allow_file_upload is True
    assert stored.allowed_file_extensions == ["jpg", "png"]
    assert stored.generation_config == {"temperature": 0.2}


def test_create_base_assistant_accepts_nested_generation_config(
    tmp_path: Path,
) -> None:
    # 観点: base assistant作成ユースケースがネストしたgeneration_configをそのまま保持すること。
    # 目的: 管理画面からResponses API向けの階層設定を保存できる契約をusecaseで固定する。
    context = _context(tmp_path)
    database = context.database

    created = create_base_assistant(
        context=context,
        actor=_admin(),
        name="Reasoning",
        description="推論設定",
        system_prompt="be helpful",
        user_prompts=[],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=20,
        allow_file_upload=False,
        allowed_file_extensions=["jpg", "jpeg", "png"],
        generation_config={"reasoning": {"effort": "low", "summary": "auto"}},
    )

    with database.connect() as conn:
        stored = BaseAssistantRepository(conn).get(created.id)

    assert stored is not None
    assert stored.generation_config == {
        "reasoning": {"effort": "low", "summary": "auto"},
    }


def test_update_base_assistant_rewrites_existing_fields(tmp_path: Path) -> None:
    # 観点: base assistant更新ユースケースが既存設定を上書きできること。
    # 目的: 編集画面が更新前後の差分計算を持たずに更新処理を委譲できるようにする。
    context = _context(tmp_path)
    created = create_base_assistant(
        context=context,
        actor=_admin(),
        name="Ops",
        description="運用用",
        system_prompt="be helpful",
        user_prompts=["base prompt"],
        connection_provider_id="openai",
        model="gpt-5-mini",
        max_history_messages=20,
        allow_file_upload=True,
        allowed_file_extensions=["jpg"],
        generation_config={"temperature": 0.2},
    )

    updated = update_base_assistant(
        context=context,
        actor=_admin(),
        base_assistant_id=created.id,
        name="Ops Updated",
        description="更新済み",
        system_prompt="be precise",
        user_prompts=["summarize"],
        connection_provider_id="openai",
        model="gpt-5",
        max_history_messages=12,
        allow_file_upload=False,
        allowed_file_extensions=["pdf", ".PDF", "md"],
        generation_config={"temperature": 0.1},
    )

    assert updated.name == "Ops Updated"
    assert updated.description == "更新済み"
    assert updated.system_prompt == "be precise"
    assert updated.user_prompts == ["summarize"]
    assert updated.model == "gpt-5"
    assert updated.max_history_messages == 12
    assert updated.allow_file_upload is False
    assert updated.allowed_file_extensions == ["pdf", "md"]
    assert updated.generation_config == {"temperature": 0.1}


def test_delete_base_assistant_logically_hides_assistant(tmp_path: Path) -> None:
    # 観点: base assistant削除ユースケースが対象を論理削除すること。
    # 目的: 管理画面が削除後の表示除外を永続化詳細なしでusecaseへ委譲できるようにする。
    context = _context(tmp_path)
    database = context.database
    created = create_base_assistant(
        context=context,
        actor=_admin(),
        name="Ops",
        description="運用用",
        system_prompt="be helpful",
        user_prompts=["base prompt"],
        connection_provider_id="openai",
        model="gpt-5-mini",
        max_history_messages=20,
        allow_file_upload=True,
        allowed_file_extensions=["jpg", "jpeg", "png"],
        generation_config={"temperature": 0.2},
    )

    deleted = delete_base_assistant(
        context=context, actor=_admin(), base_assistant_id=created.id
    )

    with database.connect() as conn:
        stored = BaseAssistantRepository(conn).get(created.id)

    assert deleted is True
    assert stored is None


def _context(tmp_path: Path) -> AdminBaseAssistantUsecaseContext:
    """admin base assistant ユースケース用のcontextを初期化して返す。"""
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    return AdminBaseAssistantUsecaseContext(
        database=database,
        load_connection_providers=_providers,
    )


def _providers() -> list[ConnectionProvider]:
    """base assistant 管理テスト用の接続先定義を返す。"""
    return [
        ConnectionProvider(
            id="openai",
            name="OpenAI",
            description="",
            api_mode="responses",
            base_url="https://api.openai.com/v1",
            api_key="secret",
            allowed_models=["gpt-5", "gpt-5-mini"],
            default_options={},
        )
    ]


def _admin() -> User:
    """base assistant 管理操作用の管理者ユーザーを返す。"""
    return User(id=1, login_name="admin", is_admin=True)
