import asyncio
import sqlite3
from collections.abc import Coroutine
from io import BytesIO
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from ...auth_password import hash_password
from ...config import load_connection_providers
from ...infrastructure import (
    AuthRepository,
    AttachmentRepository,
    AttachmentStorage,
    BaseAssistantRepository,
    Database,
    MessageRepository,
    ThreadRepository,
    utcnow,
)
from ...models import (
    AssistantGenerationConfig,
    BaseAssistant,
    PendingUpload,
    LlmMessage,
    Message,
    MessageRole,
    MessageStatus,
    ResolvedAssistant,
    Thread,
    User,
    UserInputError,
)
from ..context import UsecaseContext
from . import (
    ChatUsecaseError,
    build_chat_page,
    cancel_response,
    create_chat,
    add_message,
    delete_thread,
    get_thread_detail,
    rename_thread,
    save_message_attachments,
)

T = TypeVar("T")


class FakeResponseService:
    def __init__(self) -> None:
        self.started: list[tuple[int, list[LlmMessage], ResolvedAssistant]] = []
        self.cancelled: list[int] = []
        self.cancel_result = False

    def start_response(
        self,
        *,
        message_id: int,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> None:
        self.started.append((message_id, messages, assistant))

    async def cancel_response(self, message_id: int) -> bool:
        self.cancelled.append(message_id)
        return self.cancel_result


def test_create_chat_creates_thread_messages_and_starts_response(
    tmp_path: Path,
) -> None:
    # 観点: 新規チャット作成で保存と応答開始依頼が行われること。
    # 目的: LLM入力構築の詳細ではなく、チャット操作の副作用境界を固定する。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database

    result = run_async(
        create_chat(
            context,
            user_id=user_id,
            content="  hello  ",
            assistant_id=assistant_id,
        )
    )

    with database.connect() as conn:
        messages = MessageRepository(conn).list_by_thread(result.thread.id)

    assert result.thread.title == "hello"
    assert [message.role for message in messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert [message.status for message in messages] == [
        MessageStatus.COMPLETED,
        MessageStatus.PROCESSING,
    ]
    assert response_service.started[0][0] == result.assistant_message.id
    assert response_service.started[0][2].id == assistant_id


def test_add_message_requires_owned_thread(tmp_path: Path) -> None:
    # 観点: 他ユーザーまたは存在しないthreadへメッセージ追加できないこと。
    # 目的: 認可付きthread取得をpresentationではなくチャット操作境界に置く。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)

    with pytest.raises(ChatUsecaseError):
        run_async(
            add_message(
                context,
                user_id=user_id,
                thread_id="missing",
                content="hello",
                assistant_id=assistant_id,
            )
        )

    assert response_service.started == []


def test_add_message_appends_messages_and_starts_response(tmp_path: Path) -> None:
    # 観点: 既存threadへユーザー発言とassistant placeholderを追加できること。
    # 目的: 追加投稿時のDB更新と応答開始をひとつのusecaseとして固定する。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database
    created = run_async(
        create_chat(
            context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )
    response_service.started.clear()

    result = run_async(
        add_message(
            context,
            user_id=user_id,
            thread_id=created.thread.id,
            content="second",
            assistant_id=assistant_id,
        )
    )

    with database.connect() as conn:
        messages = MessageRepository(conn).list_by_thread(created.thread.id)

    assert result.thread.id == created.thread.id
    assert [message.content for message in messages] == [
        "first",
        "",
        "second",
        "",
    ]
    assert response_service.started[0][0] == result.assistant_message.id


def test_create_chat_rejects_blank_content(tmp_path: Path) -> None:
    # 観点: 空白だけの本文ではスレッドも応答生成も作らないこと。
    # 目的: 無効入力をDBへ入れず、ユーザー入力エラーとして上位層へ返す。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database

    with pytest.raises(UserInputError):
        run_async(
            create_chat(
                context, user_id=user_id, content="  \n", assistant_id=assistant_id
            )
        )

    with database.connect() as conn:
        assert ThreadRepository(conn).list_by_user(user_id) == []
    assert response_service.started == []


def test_create_chat_allows_attachment_only_message(tmp_path: Path) -> None:
    # 観点: 添付があれば本文なしでもチャット作成と応答開始ができること。
    # 目的: 画像だけの投稿を空本文エラーにしないusecase境界を固定する。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database
    result = run_async(
        create_chat(
            context,
            user_id=user_id,
            content=" ",
            assistant_id=assistant_id,
            uploads=[_pending_upload("photo.png", b"photo", "image/png")],
        )
    )

    with database.connect() as conn:
        messages = MessageRepository(conn).list_by_thread(result.thread.id)

    assert result.thread.title == "photo.png"
    assert messages[0].content == ""
    assert [kind.kind for kind in messages[0].kinds] == ["text", "file"]
    assert response_service.started


def test_create_chat_rolls_back_attachment_metadata_when_message_save_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 観点: 添付metadataとmessage保存が同じtransactionで失敗時に巻き戻ること。
    # 目的: 投稿usecase内のDB副作用を分割commitせず一貫した境界にする。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)
    database = context.database

    def fail_message_save(self: object, message: Message) -> Message:
        raise RuntimeError("message save failed")

    monkeypatch.setattr(
        "src.usecase.chat._support.MessageRepository.save",
        fail_message_save,
    )

    with pytest.raises(RuntimeError):
        run_async(
            create_chat(
                context,
                user_id=user_id,
                content="hello",
                assistant_id=assistant_id,
                uploads=[_pending_upload("photo.jpg", b"hello", "image/jpeg")],
            )
        )

    with database.connect() as conn:
        rows = conn.execute("select count(*) as count from attachments").fetchone()
    assert rows is not None
    assert rows["count"] == 0


def test_build_chat_page_selects_last_used_assistant(tmp_path: Path) -> None:
    # 観点: 既存スレッド表示では最後に使ったassistantが選択状態になること。
    # 目的: 画面HTMLではなくチャット表示モデルの責務として再開時の選択規則を固定する。
    context, user_id, first_assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database
    with database.connect() as conn:
        last_assistant = save_base_assistant(
            conn,
            name="Last",
            description="",
            system_prompt="system",
            user_prompts=["prefix"],
            connection_provider_id="openai",
            model="test-model",
            generation_config={},
            max_history_messages=40,
            allow_file_upload=False,
        )
        conn.commit()
    created = run_async(
        create_chat(
            context,
            user_id=user_id,
            content="first",
            assistant_id=first_assistant_id,
        )
    )
    response_service.started.clear()
    run_async(
        add_message(
            context,
            user_id=user_id,
            thread_id=created.thread.id,
            content="second",
            assistant_id=last_assistant.id,
        )
    )

    page = build_chat_page(context, user_id=user_id, thread_id=created.thread.id)

    assert page is not None
    assert page.selected_assistant_id == last_assistant.id


def test_build_chat_page_exposes_assistant_allowed_file_extensions(
    tmp_path: Path,
) -> None:
    # 観点: チャット画面表示モデルがassistantごとの許可拡張子を持つこと。
    # 目的: ファイル選択UIをサーバー側の添付ポリシーと同じ情報で制御できるようにする。
    context, user_id, assistant_id, _ = _context_with_user(
        tmp_path,
        allowed_file_extensions=["txt", "md"],
    )

    page = build_chat_page(context, user_id=user_id)

    assert page is not None
    assert page.assistant_allowed_file_extensions[assistant_id] == ["txt", "md"]


def test_delete_thread_requires_owned_thread_and_hides_it(tmp_path: Path) -> None:
    # 観点: 所有しているthreadだけを論理削除し、以後の詳細取得から隠すこと。
    # 目的: HTTP routeが削除認可とDB更新手順を持たずusecaseへ委譲できるようにする。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)
    created = run_async(
        create_chat(
            context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )

    deleted = delete_thread(context, user_id=user_id, thread_id=created.thread.id)
    missing = get_thread_detail(
        context, thread_id=created.thread.id, user_id=user_id
    )

    assert deleted is True
    assert missing is None
    with pytest.raises(ChatUsecaseError):
        run_async(
            add_message(
                context,
                user_id=user_id,
                thread_id=created.thread.id,
                content="second",
                assistant_id=assistant_id,
            )
        )


def test_rename_thread_updates_owned_thread_title(tmp_path: Path) -> None:
    # 観点: 所有しているthreadのタイトルを編集できること。
    # 目的: タイトル編集の永続化責務をHTTP層ではなくusecaseへ閉じ込める。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)
    database = context.database
    created = run_async(
        create_chat(
            context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )

    renamed = rename_thread(
        context,
        user_id=user_id,
        thread_id=created.thread.id,
        title="  renamed title  ",
    )

    with database.connect() as conn:
        stored = ThreadRepository(conn).get(created.thread.id, user_id)

    assert renamed.title == "renamed title"
    assert stored is not None
    assert stored.title == "renamed title"


def test_cancel_response_marks_processing_message_failed_when_no_running_job(
    tmp_path: Path,
) -> None:
    # 観点: response serviceが実行中jobを持たないprocessing messageをfailedへ収束すること。
    # 目的: キャンセル時の永続化fallbackをHTTP routeではなくusecase責務として固定する。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database
    with database.connect() as conn:
        thread = save_thread(conn, user_id, "cancel me")
        save_message(
            conn,
            thread_id=thread.id,
            role=MessageRole.USER,
            content="cancel me",
            status=MessageStatus.COMPLETED,
            assistant_id=assistant_id,
        )
        assistant = save_message(
            conn,
            thread_id=thread.id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.PROCESSING,
            assistant_id=assistant_id,
        )
        conn.commit()

    run_async(
        cancel_response(
            context,
            user_id=user_id,
            thread_id=thread.id,
            message_id=assistant.id,
        )
    )

    with database.connect() as conn:
        message = MessageRepository(conn).get(assistant.id)
    assert response_service.cancelled == [assistant.id]
    assert message.status is MessageStatus.FAILED


def test_save_message_attachments_persists_allowed_upload(tmp_path: Path) -> None:
    # 観点: 添付許可されたassistantでは許可拡張子のファイル実体とmetadataを保存できること。
    # 目的: assistant別の添付ポリシーとtransactionをpresentationではなくchat usecaseへ閉じる。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)
    database = context.database
    upload = _pending_upload("photo.jpg", b"image", "image/jpeg")

    attachments = asyncio.run(
        save_message_attachments(
            context,
            user_id=user_id,
            assistant_id=assistant_id,
            uploads=[upload],
        )
    )

    with database.connect() as conn:
        stored = AttachmentRepository(conn).get_for_user(
            attachment_id=attachments[0].id,
            user_id=user_id,
        )

    assert len(attachments) == 1
    assert stored == attachments[0]
    assert (tmp_path / attachments[0].stored_path).read_bytes() == b"image"


def test_save_message_attachments_rejects_extension_outside_assistant_policy(
    tmp_path: Path,
) -> None:
    # 観点: 添付許可assistantでも許可外拡張子は保存前に拒否すること。
    # 目的: ファイル種別の入口制御をアプリ全体ではなくassistant個別設定で固定する。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)

    with pytest.raises(UserInputError, match="file extension is not allowed"):
        asyncio.run(
            save_message_attachments(
                context,
                user_id=user_id,
                assistant_id=assistant_id,
                uploads=[_pending_upload("memo.txt", b"hello", "text/plain")],
            )
        )

    with context.database.connect() as conn:
        rows = conn.execute("select count(*) as count from attachments").fetchone()
    assert rows is not None
    assert rows["count"] == 0


def test_save_message_attachments_accepts_assistant_custom_extension(
    tmp_path: Path,
) -> None:
    # 観点: assistantが個別に許可した拡張子は既定画像以外でも保存できること。
    # 目的: 読み込み可能ファイル種別をassistantごとの設定として扱う。
    context, user_id, assistant_id, _ = _context_with_user(
        tmp_path,
        allowed_file_extensions=["txt"],
    )

    attachments = asyncio.run(
        save_message_attachments(
            context,
            user_id=user_id,
            assistant_id=assistant_id,
            uploads=[_pending_upload("memo.txt", b"hello", "text/plain")],
        )
    )

    assert attachments[0].original_filename == "memo.txt"


def test_save_message_attachments_rejects_disallowed_assistant_without_side_effect(
    tmp_path: Path,
) -> None:
    # 観点: 添付不可assistantではファイル保存もmetadata登録も行わないこと。
    # 目的: 許可判定を副作用より前にusecaseで固定する。
    context, user_id, assistant_id, _ = _context_with_user(
        tmp_path,
        allow_file_upload=False,
    )
    database = context.database

    with pytest.raises(UserInputError):
        asyncio.run(
            save_message_attachments(
                context,
                user_id=user_id,
                assistant_id=assistant_id,
                uploads=[_pending_upload("memo.txt", b"hello", "text/plain")],
            )
        )

    with database.connect() as conn:
        rows = conn.execute("select count(*) as count from attachments").fetchone()
    assert rows is not None
    assert rows["count"] == 0
    assert not any(tmp_path.glob(f"{user_id}/*"))


def _context_with_user(
    tmp_path: Path,
    *,
    allow_file_upload: bool = True,
    allowed_file_extensions: list[str] | None = None,
) -> tuple[UsecaseContext, int, str, FakeResponseService]:
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        created = save_base_assistant(
            conn,
            name="Default",
            description="",
            system_prompt="system",
            user_prompts=["prefix"],
            connection_provider_id="openai",
            model="test-model",
            generation_config={},
            max_history_messages=40,
            allow_file_upload=allow_file_upload,
            allowed_file_extensions=allowed_file_extensions
            or ["jpg", "jpeg", "png"],
        )
        conn.commit()
    (tmp_path / "connection_providers.json").write_text(
        """
        {
          "providers": [
            {
              "id": "openai",
              "name": "OpenAI",
              "api_mode": "chat_completions",
              "api_key": "test",
              "base_url": null,
              "allowed_models": ["test-model"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    response_service = FakeResponseService()
    context = UsecaseContext(
        database=database,
        password_pepper="pepper",
        response_service=response_service,
        uploads_dir=tmp_path,
        attachment_storage=AttachmentStorage(tmp_path),
        load_connection_providers=lambda: load_connection_providers(tmp_path),
    )
    return context, user.id, created.id, response_service


def _upload(filename: str, body: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        BytesIO(body),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _pending_upload(filename: str, body: bytes, content_type: str) -> PendingUpload:
    upload = _upload(filename, body, content_type)
    return PendingUpload(
        filename=upload.filename or "",
        content_type=upload.content_type or "",
        read=upload.read,
        close=upload.close,
    )


def run_async(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def save_user(
    conn: sqlite3.Connection,
    password_pepper: str,
    login_name: str,
    password: str,
) -> User:
    return AuthRepository(conn).save(
        User(id=0, login_name=login_name),
        password_hash=hash_password(password, password_pepper),
    )


def save_base_assistant(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str,
    system_prompt: str,
    user_prompts: list[str],
    connection_provider_id: str,
    model: str,
    generation_config: AssistantGenerationConfig,
    max_history_messages: int,
    allow_file_upload: bool,
    allowed_file_extensions: list[str] | None = None,
) -> BaseAssistant:
    return BaseAssistantRepository(conn).save(
        BaseAssistant(
            id=str(uuid4()),
            name=name,
            description=description,
            system_prompt=system_prompt,
            user_prompts=user_prompts,
            connection_provider_id=connection_provider_id,
            model=model,
            generation_config=generation_config,
            max_history_messages=max_history_messages,
            allow_file_upload=allow_file_upload,
            allowed_file_extensions=allowed_file_extensions or ["jpg", "jpeg", "png"],
        )
    )


def save_thread(conn: sqlite3.Connection, user_id: int, title: str) -> Thread:
    now = utcnow()
    return ThreadRepository(conn).save(
        Thread(
            id=str(uuid4()),
            user_id=user_id,
            title=title.strip()[:80] or "New chat",
            created_at=now,
            updated_at=now,
        )
    )


def save_message(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    role: MessageRole,
    content: str,
    status: MessageStatus,
    assistant_id: str | None = None,
) -> Message:
    now = utcnow()
    return MessageRepository(conn).save(
        Message(
            id=0,
            thread_id=thread_id,
            role=role,
            content=content,
            status=status,
            assistant_id=assistant_id,
            created_at=now,
            updated_at=now,
        )
    )
