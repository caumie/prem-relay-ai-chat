import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import pytest

from ...service.password import hash_password
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
    LlmMessage,
    Message,
    MessageRole,
    MessageStatus,
    PendingUpload,
    ResolvedAssistant,
    Thread,
    User,
    UserInputError,
)
from ...service.response_service import StreamEvent
from . import ChatUsecaseContext
from . import (
    ChatUsecaseError,
    build_chat_page,
    cancel_response,
    create_chat,
    add_message,
    delete_thread,
    get_attachment_download,
    prepare_response_stream,
    get_thread_detail,
    rename_thread,
    save_message_attachments,
    stream_response_events,
)

T = TypeVar("T")


class FakeResponseService:
    def __init__(self) -> None:
        self.started: list[tuple[int, list[LlmMessage], ResolvedAssistant]] = []
        self.cancelled: list[int] = []
        self.cancel_result = False
        self.cancel_callback: Callable[[int], None] | None = None
        self.events: list[StreamEvent] = []
        self.start_error: Exception | None = None

    def start_response(
        self,
        *,
        message_id: int,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> None:
        self.started.append((message_id, messages, assistant))
        if self.start_error is not None:
            raise self.start_error

    async def cancel_response(self, message_id: int) -> bool:
        self.cancelled.append(message_id)
        if self.cancel_callback is not None:
            self.cancel_callback(message_id)
        return self.cancel_result

    async def stream_events(self, message: Message) -> AsyncIterator[StreamEvent]:
        for event in self.events:
            yield event


def test_create_chat_creates_thread_messages_and_starts_response(
    tmp_path: Path,
) -> None:
    # 観点: 新規チャット作成で保存と応答開始依頼が行われること。
    # 目的: LLM入力構築の詳細ではなく、チャット操作の副作用境界を固定する。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database

    result = run_async(
        create_chat(
            context=context,
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


def test_create_chat_marks_placeholder_failed_when_response_start_fails(
    tmp_path: Path,
) -> None:
    # 観点: placeholderのcommit後に応答開始が失敗してもprocessingが残らないこと。
    # 目的: local Jobなしのprocessingを通常経路で作らず、再接続を孤児回収に使わない。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    response_service.start_error = RuntimeError("start failed")

    with pytest.raises(RuntimeError, match="start failed"):
        run_async(
            create_chat(
                context=context,
                user_id=user_id,
                content="hello",
                assistant_id=assistant_id,
            )
        )

    with context.database.connect() as conn:
        threads = ThreadRepository(conn).list_by_user(user_id)
        messages = MessageRepository(conn).list_by_thread(threads[0].id)
    assert messages[-1].role is MessageRole.ASSISTANT
    assert messages[-1].status is MessageStatus.FAILED


def test_add_message_marks_placeholder_failed_when_response_start_fails(
    tmp_path: Path,
) -> None:
    # 観点: 既存threadへの追加でも応答開始失敗後にprocessingを残さないこと。
    # 目的: 新規chatと追加投稿でpost-commit補償の有無を分岐させない。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    created = run_async(
        create_chat(
            context=context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )
    response_service.start_error = RuntimeError("start failed")

    with pytest.raises(RuntimeError, match="start failed"):
        run_async(
            add_message(
                context=context,
                user_id=user_id,
                thread_id=created.thread.id,
                content="second",
                assistant_id=assistant_id,
            )
        )

    with context.database.connect() as conn:
        messages = MessageRepository(conn).list_by_thread(created.thread.id)
    assert messages[-1].role is MessageRole.ASSISTANT
    assert messages[-1].status is MessageStatus.FAILED


def test_add_message_requires_owned_thread(tmp_path: Path) -> None:
    # 観点: 他ユーザーまたは存在しないthreadへメッセージ追加できないこと。
    # 目的: 認可付きthread取得を添付保存より前のチャット操作境界に置く。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)

    with pytest.raises(ChatUsecaseError):
        run_async(
            add_message(
                context=context,
                user_id=user_id,
                thread_id="missing",
                content="hello",
                assistant_id=assistant_id,
                uploads=[_pending_upload("photo.jpg", b"image", "image/jpeg")],
            )
        )

    assert response_service.started == []
    assert not any(tmp_path.glob(f"{user_id}/*"))


def test_add_message_appends_messages_and_starts_response(tmp_path: Path) -> None:
    # 観点: 既存threadへユーザー発言とassistant placeholderを追加できること。
    # 目的: 追加投稿時のDB更新と応答開始をひとつのusecaseとして固定する。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database
    created = run_async(
        create_chat(
            context=context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )
    response_service.started.clear()

    result = run_async(
        add_message(
            context=context,
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
                context=context,
                user_id=user_id,
                content="  \n",
                assistant_id=assistant_id,
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
            context=context,
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


def test_create_chat_removes_attachment_when_message_save_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 観点: message保存失敗時は添付metadataと実ファイルが残らないこと。
    # 目的: DB rollbackとファイル補償を投稿usecaseの一貫した失敗境界にする。
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
                context=context,
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
    assert not any(tmp_path.glob(f"{user_id}/*"))


def test_add_message_removes_uploaded_file_when_message_save_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 観点: 既存threadへの投稿保存失敗時は添付metadataと実ファイルが残らないこと。
    # 目的: DB rollbackでは戻せないファイル実体を投稿usecaseの補償処理で削除する。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)
    created = run_async(
        create_chat(
            context=context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )

    def fail_message_save(self: object, message: Message) -> Message:
        raise RuntimeError("message save failed")

    monkeypatch.setattr(
        "src.usecase.chat._support.MessageRepository.save",
        fail_message_save,
    )

    with pytest.raises(RuntimeError, match="message save failed"):
        run_async(
            add_message(
                context=context,
                user_id=user_id,
                thread_id=created.thread.id,
                content="second",
                assistant_id=assistant_id,
                uploads=[_pending_upload("photo.jpg", b"image", "image/jpeg")],
            )
        )

    with context.database.connect() as conn:
        rows = conn.execute("select count(*) as count from attachments").fetchone()
    assert rows is not None
    assert rows["count"] == 0
    assert not any(tmp_path.glob(f"{user_id}/*"))


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
            context=context,
            user_id=user_id,
            content="first",
            assistant_id=first_assistant_id,
        )
    )
    response_service.started.clear()
    run_async(
        add_message(
            context=context,
            user_id=user_id,
            thread_id=created.thread.id,
            content="second",
            assistant_id=last_assistant.id,
        )
    )

    page = build_chat_page(context=context, user_id=user_id, thread_id=created.thread.id)

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

    page = build_chat_page(context=context, user_id=user_id)

    assert page is not None
    assert page.assistant_allowed_file_extensions[assistant_id] == ["txt", "md"]


def test_delete_thread_requires_owned_thread_and_hides_it(tmp_path: Path) -> None:
    # 観点: 所有しているthreadだけを論理削除し、以後の詳細取得から隠すこと。
    # 目的: HTTP routeが削除認可とDB更新手順を持たずusecaseへ委譲できるようにする。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)
    created = run_async(
        create_chat(
            context=context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )

    deleted = delete_thread(context=context, user_id=user_id, thread_id=created.thread.id)
    missing = get_thread_detail(
        context=context, thread_id=created.thread.id, user_id=user_id
    )

    assert deleted is True
    assert missing is None
    with pytest.raises(ChatUsecaseError):
        run_async(
            add_message(
                context=context,
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
            context=context,
            user_id=user_id,
            content="first",
            assistant_id=assistant_id,
        )
    )

    renamed = rename_thread(
        context=context,
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
            context=context,
            user_id=user_id,
            thread_id=thread.id,
            message_id=assistant.id,
        )
    )

    with database.connect() as conn:
        message = MessageRepository(conn).get(assistant.id)
    assert response_service.cancelled == [assistant.id]
    assert message.status is MessageStatus.FAILED


def test_cancel_response_does_not_overwrite_terminal_state_won_during_await(
    tmp_path: Path,
) -> None:
    # 観点: cancelのawait中にcompletedへ確定した応答をfailedで上書きしないこと。
    # 目的: Jobを持たないworkerの後着cancelも条件付きterminal更新に従わせる。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    created = run_async(
        create_chat(
            context=context,
            user_id=user_id,
            content="complete while cancelling",
            assistant_id=assistant_id,
        )
    )

    def complete_elsewhere(message_id: int) -> None:
        with context.database.connect() as conn:
            repo = MessageRepository(conn)
            repo.update(
                replace(
                    repo.get(message_id),
                    content="winner",
                    status=MessageStatus.COMPLETED,
                    updated_at=utcnow(),
                )
            )
            conn.commit()

    response_service.cancel_callback = complete_elsewhere
    response_service.cancel_result = False

    run_async(
        cancel_response(
            context=context,
            user_id=user_id,
            thread_id=created.thread.id,
            message_id=created.assistant_message.id,
        )
    )

    with context.database.connect() as conn:
        stored = MessageRepository(conn).get(created.assistant_message.id)
    assert stored.status is MessageStatus.COMPLETED
    assert stored.content == "winner"


def test_stream_response_events_returns_runtime_stream_after_ownership_check(
    tmp_path: Path,
) -> None:
    # 観点: SSE再接続がprocessing応答の生成を改めて開始しないこと。
    # 目的: 別processで実行中の応答を重複生成せず、購読だけをserviceへ委譲する。
    context, user_id, assistant_id, response_service = _context_with_user(tmp_path)
    database = context.database
    response_service.events = [
        StreamEvent("status", message_id=2, status="streaming"),
        StreamEvent("delta", message_id=2, delta="hello"),
        StreamEvent("done", message_id=2),
    ]
    created = run_async(
        create_chat(
            context=context,
            user_id=user_id,
            content="hello",
            assistant_id=assistant_id,
        )
    )
    response_service.started.clear()

    response_message = prepare_response_stream(
        context=context,
        user_id=user_id,
        thread_id=created.thread.id,
        response_id=created.assistant_message.id,
    )

    events = run_async(
        _collect_stream(
            stream_response_events(
                context=context,
                response_message=response_message,
            )
        )
    )

    with database.connect() as conn:
        stored = MessageRepository(conn).get(created.assistant_message.id)
    assert [event.type for event in events] == ["status", "delta", "done"]
    assert response_service.started == []
    assert stored.id == created.assistant_message.id


def test_get_attachment_download_returns_owned_file_response_metadata(
    tmp_path: Path,
) -> None:
    # 観点: 添付ダウンロードは所有者検証済みmetadataと実ファイルパスをまとめて返すこと。
    # 目的: presentationがattachment storageや保存相対パス解決を直接持たない境界を固定する。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)

    attachments = run_async(
        save_message_attachments(
            context=context,
            user_id=user_id,
            assistant_id=assistant_id,
            uploads=[_pending_upload("photo.jpg", b"image", "image/jpeg")],
        )
    )

    download = get_attachment_download(
        context=context,
        attachment_id=attachments[0].id,
        user_id=user_id,
    )

    assert download is not None
    assert download.filename == "photo.jpg"
    assert download.media_type == "image/jpeg"
    assert download.path.read_bytes() == b"image"


def test_save_message_attachments_persists_allowed_upload(tmp_path: Path) -> None:
    # 観点: 添付許可されたassistantでは許可拡張子のファイル実体とmetadataを保存できること。
    # 目的: assistant別の添付ポリシーとtransactionをpresentationではなくchat usecaseへ閉じる。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)
    database = context.database
    upload = _pending_upload("photo.jpg", b"image", "image/jpeg")

    attachments = asyncio.run(
        save_message_attachments(
            context=context,
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


def test_save_message_attachments_accepts_ten_files_and_rejects_eleven(
    tmp_path: Path,
) -> None:
    # 観点: 1メッセージには10件まで添付でき、11件目からは拒否すること。
    # 目的: サーバー側の添付上限を利用者へ提示する上限値と一致させる。
    context, user_id, assistant_id, _ = _context_with_user(
        tmp_path,
        allowed_file_extensions=["txt"],
    )
    ten_uploads = [
        _pending_upload(f"memo-{index}.txt", b"hello", "text/plain")
        for index in range(10)
    ]

    attachments = asyncio.run(
        save_message_attachments(
            context=context,
            user_id=user_id,
            assistant_id=assistant_id,
            uploads=ten_uploads,
        )
    )

    assert len(attachments) == 10
    with pytest.raises(UserInputError, match=r"too many attachments \(maximum: 10\)"):
        asyncio.run(
            save_message_attachments(
                context=context,
                user_id=user_id,
                assistant_id=assistant_id,
                uploads=[
                    _pending_upload(
                        f"extra-{index}.txt", b"hello", "text/plain"
                    )
                    for index in range(11)
                ],
            )
        )


def test_save_message_attachments_removes_prior_file_when_later_save_fails(
    tmp_path: Path,
) -> None:
    # 観点: 複数添付の途中で保存に失敗しても先に保存した実ファイルが残らないこと。
    # 目的: 添付保存処理単体でも部分成功による孤児ファイルを作らない。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)

    with pytest.raises(UserInputError, match="attachment is empty"):
        run_async(
            save_message_attachments(
                context=context,
                user_id=user_id,
                assistant_id=assistant_id,
                uploads=[
                    _pending_upload("first.jpg", b"image", "image/jpeg"),
                    _pending_upload("second.jpg", b"", "image/jpeg"),
                ],
            )
        )

    with context.database.connect() as conn:
        rows = conn.execute("select count(*) as count from attachments").fetchone()
    assert rows is not None
    assert rows["count"] == 0
    assert not any(tmp_path.glob(f"{user_id}/*"))


def test_save_message_attachments_rejects_extension_outside_assistant_policy(
    tmp_path: Path,
) -> None:
    # 観点: 添付許可assistantでも許可外拡張子は保存前に拒否すること。
    # 目的: ファイル種別の入口制御をアプリ全体ではなくassistant個別設定で固定する。
    context, user_id, assistant_id, _ = _context_with_user(tmp_path)

    with pytest.raises(UserInputError, match="file extension is not allowed"):
        asyncio.run(
            save_message_attachments(
                context=context,
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
            context=context,
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
                context=context,
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
) -> tuple[ChatUsecaseContext, int, str, FakeResponseService]:
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
    context = ChatUsecaseContext(
        database=database,
        response_service=response_service,
        uploads_dir=tmp_path,
        attachment_storage=AttachmentStorage(tmp_path),
        load_connection_providers=lambda: load_connection_providers(tmp_path),
    )
    return context, user.id, created.id, response_service


def _pending_upload(filename: str, body: bytes, content_type: str) -> PendingUpload:
    stream = BytesIO(body)

    async def read(size: int) -> bytes:
        return stream.read(size)

    async def close() -> None:
        stream.close()

    return PendingUpload(
        filename=filename,
        content_type=content_type,
        read=read,
        close=close,
    )


async def _collect_stream(
    stream: AsyncIterator[StreamEvent],
) -> list[StreamEvent]:
    return [event async for event in stream]


def run_async(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def save_user(
    conn: sqlite3.Connection,
    password_pepper: str,
    login_name: str,
    password: str,
) -> User:
    return AuthRepository(conn).create(
        login_name=login_name,
        is_admin=False,
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
