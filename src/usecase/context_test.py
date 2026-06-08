"""usecase 実行依存を束ねる共有 context の契約をテストする。"""

from pathlib import Path

from src.infrastructure import AttachmentStorage, Database
from src.models import ConnectionProvider
from src.usecase.context import UsecaseContext
from src.usecase.test_support import FakeResponseStarter


def test_usecase_context_keeps_runtime_dependencies_together(tmp_path: Path) -> None:
    # 観点: usecase 実行に必要な依存が共有contextに明示的に束ねられること。
    # 目的: module global configure に依存せず、app配線から依存を渡せる契約を固定する。
    database = Database(tmp_path / "data.sqlite")
    storage = AttachmentStorage(tmp_path / "uploads")
    response_starter = FakeResponseStarter()

    context = UsecaseContext(
        database=database,
        password_pepper="pepper",
        response_service=response_starter,
        uploads_dir=tmp_path / "uploads",
        attachment_storage=storage,
        load_connection_providers=lambda: [],
    )

    assert context.database is database
    assert context.password_pepper == "pepper"
    assert context.response_service is response_starter
    assert context.attachment_storage is storage
    assert context.load_connection_providers() == []


def test_usecase_contexts_do_not_share_mutable_runtime_state(tmp_path: Path) -> None:
    # 観点: 複数contextが同一プロセス内で別々の依存を保持できること。
    # 目的: 複数appやテストがmodule global上書きで混線しない状態を固定する。
    first_provider = ConnectionProvider(
        id="first",
        name="First",
        description="",
        api_mode="chat_completions",
        base_url=None,
        api_key="",
        allowed_models=[],
        default_options={},
    )
    second_provider = ConnectionProvider(
        id="second",
        name="Second",
        description="",
        api_mode="responses",
        base_url=None,
        api_key="",
        allowed_models=[],
        default_options={},
    )

    first = UsecaseContext(
        database=Database(tmp_path / "first.sqlite"),
        password_pepper="first-pepper",
        response_service=FakeResponseStarter(),
        uploads_dir=tmp_path / "first-uploads",
        attachment_storage=AttachmentStorage(tmp_path / "first-uploads"),
        load_connection_providers=lambda: [first_provider],
    )
    second = UsecaseContext(
        database=Database(tmp_path / "second.sqlite"),
        password_pepper="second-pepper",
        response_service=FakeResponseStarter(),
        uploads_dir=tmp_path / "second-uploads",
        attachment_storage=AttachmentStorage(tmp_path / "second-uploads"),
        load_connection_providers=lambda: [second_provider],
    )

    assert first.database.db_path != second.database.db_path
    assert first.password_pepper != second.password_pepper
    assert first.load_connection_providers()[0].id == "first"
    assert second.load_connection_providers()[0].id == "second"
