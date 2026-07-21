import asyncio
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.service.password import hash_password
from src.models import (
    LlmMessage,
    Message,
    MessageKind,
    MessageRole,
    MessageStatus,
    ResolvedAssistant,
    Thread,
    User,
)
from src.infrastructure import (
    AuthRepository,
    Database,
    MessageRepository,
    ThreadRepository,
    utcnow,
)
from src.service.response_service import (
    ResponseJobStatus,
    ResponseService,
    StreamEvent,
)


class SuccessfulResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="hello")
        yield StreamEvent("delta", delta=" world")


class ReasoningResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("reasoning_delta", reasoning_delta="thinking")
        yield StreamEvent("delta", delta="answer")


class FailingResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="partial")
        raise RuntimeError("boom")


class ReasoningFailingResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("reasoning_delta", reasoning_delta="thinking")
        yield StreamEvent("delta", delta="partial")
        raise RuntimeError("boom")


class WaitingResponder:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="partial")
        self.started.set()
        await asyncio.Event().wait()


class ReleasableResponder:
    def __init__(self) -> None:
        self.first_delta_published = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="hello")
        self.first_delta_published.set()
        await self.release.wait()
        yield StreamEvent("delta", delta=" world")


def test_stream_event_serializes_only_present_fields() -> None:
    # 観点: SSEへ流すイベントが空値を含まずJSON payloadとして表現されること。
    # 目的: presentation層がイベント型ごとの細かな整形を持たない境界を固定する。
    event = StreamEvent("delta", message_id=10, delta="hello")

    assert (
        event.to_sse() == 'data: {"type":"delta","message_id":10,"delta":"hello"}\n\n'
    )


def test_stream_event_serializes_reasoning_delta() -> None:
    # 観点: reasoning更新を本文deltaと別のSSE payloadとして表現できること。
    # 目的: UIが本文とreasoningを別領域へ描画できるバックエンド契約を固定する。
    event = StreamEvent("reasoning_delta", message_id=10, reasoning_delta="thinking")

    assert (
        event.to_sse()
        == 'data: {"type":"reasoning_delta","message_id":10,"reasoning_delta":"thinking"}\n\n'
    )


def test_response_service_persists_completed_message(tmp_path: Path) -> None:
    # 観点: LLM応答が成功したらassistant messageをcompletedとして永続化すること。
    # 目的: 応答生成のDB更新責務をFastAPI routeではなくresponse_serviceへ閉じる。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())

    asyncio.run(
        service.run_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
    )

    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)

    assert message.status is MessageStatus.COMPLETED
    assert message.content == "hello world"


def test_response_service_persists_reasoning_kind(tmp_path: Path) -> None:
    # 観点: LLM応答のreasoningを本文とは別kindとして永続化すること。
    # 目的: 再表示時に本文とthinking領域を混ぜずに復元できる保存境界を固定する。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=ReasoningResponder())

    asyncio.run(
        service.run_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
    )

    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)

    assert message.content == "answer"
    assert [(kind.kind, kind.content) for kind in message.kinds] == [
        ("text", "answer"),
        ("reasoning", "thinking"),
    ]


def test_response_service_persists_failed_message_with_partial_content(
    tmp_path: Path,
) -> None:
    # 観点: LLM応答が失敗したら部分本文を残してassistant messageをfailedにすること。
    # 目的: ユーザーが明示的に再送/削除でリカバーできる永続状態を固定する。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=FailingResponder())

    asyncio.run(
        service.run_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
    )

    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)

    assert message.status is MessageStatus.FAILED
    assert message.content == "partial"


def test_response_service_persists_failed_message_with_partial_reasoning(
    tmp_path: Path,
) -> None:
    # 観点: 失敗時も途中まで得たreasoningを本文とは別kindとして残すこと。
    # 目的: 部分本文を残す既存リカバリ方針をreasoningにも適用する。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=ReasoningFailingResponder())

    asyncio.run(
        service.run_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
    )

    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)

    assert message.status is MessageStatus.FAILED
    assert [(kind.kind, kind.content) for kind in message.kinds] == [
        ("text", "partial"),
        ("reasoning", "thinking"),
    ]


def test_response_service_does_not_raise_when_message_is_deleted_during_generation(
    tmp_path: Path,
) -> None:
    # 観点: 生成中に対象messageが削除されてもTask例外が漏れないこと。
    # 目的: terminal永続化時のKeyErrorが元の生成Taskを未処理例外にしない。
    database, message_id = _database_with_assistant_message(tmp_path)
    with database.connect() as conn:
        assert MessageRepository(conn).delete(message_id) is True
        conn.commit()

    service = ResponseService(database=database, responder=SuccessfulResponder())

    asyncio.run(
        service.run_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
    )

    # 終端jobは購読がなくても即時回収される。
    assert service.jobs.get(message_id) is None


def test_response_service_uses_existing_terminal_state_when_finalize_loses_race(
    tmp_path: Path,
) -> None:
    # 観点: 別処理が先にfailedへ確定した場合、そのDB状態をsuccessで上書きしないこと。
    # 目的: 条件付きUPDATEが0件だった時に古いprocessing状態を終端結果として使わない。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())
    job = service.jobs.get_or_create(message_id)
    with database.connect() as conn:
        repo = MessageRepository(conn)
        update_message(
            conn,
            repo.get(message_id),
            content="cancelled elsewhere",
            status=MessageStatus.FAILED,
            kinds=[MessageKind(kind="reasoning", content="remote reasoning")],
        )
        conn.commit()

    asyncio.run(
        service.run_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
    )

    assert job.status is ResponseJobStatus.FAILED
    assert job.error == "failed"
    assert job.content_buffer == "cancelled elsewhere"
    assert job.reasoning_buffer == "remote reasoning"


def test_response_service_uses_completed_state_when_finalize_loses_race(
    tmp_path: Path,
) -> None:
    # 観点: Provider失敗より先にcompletedが確定した場合、DB状態を維持すること。
    # 目的: 条件付きUPDATEが0件だった時に古いprocessing状態で上書きしない。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=FailingResponder())
    job = service.jobs.get_or_create(message_id)
    with database.connect() as conn:
        repo = MessageRepository(conn)
        update_message(
            conn,
            repo.get(message_id),
            content="winner",
            status=MessageStatus.COMPLETED,
        )
        conn.commit()

    asyncio.run(
        service.run_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
    )

    assert job.status is ResponseJobStatus.COMPLETED
    assert job.content_buffer == "winner"


def test_response_service_cancels_running_response_with_partial_content(
    tmp_path: Path,
) -> None:
    # 観点: 実行中の応答生成を中断すると部分本文を残してfailedへ収束すること。
    # 目的: ブラウザの接続切断だけに頼らず、サーバー側の生成タスクを明示的に止める。
    database, message_id = _database_with_assistant_message(tmp_path)
    responder = WaitingResponder()
    service = ResponseService(database=database, responder=responder)

    async def run_and_cancel() -> bool:
        service.start_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
        await responder.started.wait()
        return await service.cancel_response(message_id)

    cancelled = asyncio.run(run_and_cancel())

    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)

    assert cancelled is True
    assert message.status is MessageStatus.FAILED
    assert message.content == "partial"


def test_response_service_keeps_running_task_when_start_is_called_again(
    tmp_path: Path,
) -> None:
    # 観点: 同一messageへの開始が重複して呼ばれても実行中taskを上書きしないこと。
    # 目的: キャンセル時にAIプロバイダ接続を持つ本物のtaskを確実に止める。
    database, message_id = _database_with_assistant_message(tmp_path)
    responder = WaitingResponder()
    service = ResponseService(database=database, responder=responder)

    async def run_duplicate_start_and_cancel() -> tuple[bool, bool]:
        service.start_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
        await responder.started.wait()
        job = service.jobs.get(message_id)
        assert job is not None
        original_task = job.task
        service.start_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
        same_task = job.task is original_task
        cancelled = await service.cancel_response(message_id)
        task_done = original_task.done() if original_task else False
        return same_task, cancelled and task_done

    same_task, cancelled_original = asyncio.run(run_duplicate_start_and_cancel())

    assert same_task is True
    assert cancelled_original is True


def test_response_service_replaces_stale_task_from_stopped_loop(
    tmp_path: Path,
) -> None:
    # 観点: 別の停止済みevent loopに紐づくpending taskは実行中扱いしないこと。
    # 目的: 明示的な開始呼出しが停止済みloopのTaskに阻害されないようにする。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())
    stale_loop = asyncio.new_event_loop()
    stale_task = stale_loop.create_task(asyncio.sleep(60))
    job = service.jobs.get_or_create(message_id)
    job.task = stale_task

    async def start_with_current_loop() -> asyncio.Task[None] | None:
        service.start_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
        return job.task

    replacement = asyncio.run(start_with_current_loop())
    stale_task.cancel()
    stale_loop.run_until_complete(asyncio.gather(stale_task, return_exceptions=True))
    stale_loop.close()

    assert replacement is not stale_task
    assert replacement is not None


def test_response_service_streams_running_job_events_and_persists_completed(
    tmp_path: Path,
) -> None:
    # 観点: 実行中jobのSSE購読で既存bufferと以後の最新full/doneを受け取れること。
    # 目的: Event通知を蓄積せず最新snapshotを配信し、完了を永続化する契約を固定する。
    database, message_id = _database_with_assistant_message(tmp_path)
    responder = ReleasableResponder()
    service = ResponseService(database=database, responder=responder)

    async def run_stream() -> list[StreamEvent]:
        service.start_response(
            message_id=message_id,
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant(),
        )
        await responder.first_delta_published.wait()
        with database.connect() as conn:
            message = MessageRepository(conn).get(message_id)
        collect_task = asyncio.create_task(_collect_stream(service, message))
        await asyncio.sleep(0)
        responder.release.set()
        return await collect_task

    events = asyncio.run(run_stream())

    assert events == [
        StreamEvent("status", message_id=message_id, status="streaming"),
        StreamEvent("full", message_id=message_id, content="hello"),
        StreamEvent("full", message_id=message_id, content="hello world"),
        StreamEvent("done", message_id=message_id),
    ]
    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)
    assert message.status is MessageStatus.COMPLETED
    assert message.content == "hello world"


def test_response_service_stream_replays_active_reasoning_buffer(
    tmp_path: Path,
) -> None:
    # 観点: 生成中jobへ再接続したときreasoning全文も復元されること。
    # 目的: 直列streamでも保存先が異なる情報を個別に再送できる状態管理を固定する。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())
    job = service.jobs.get_or_create(message_id)
    job.status = ResponseJobStatus.COMPLETED
    job.publish(StreamEvent("reasoning_delta", reasoning_delta="thinking"))
    job.publish(StreamEvent("delta", delta="answer"))

    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)

    events = asyncio.run(_collect_stream(service, message))

    assert events == [
        StreamEvent("status", message_id=message_id, status="completed"),
        StreamEvent("full", message_id=message_id, content="answer"),
        StreamEvent("reasoning", message_id=message_id, reasoning="thinking"),
        StreamEvent("done", message_id=message_id),
    ]


def test_response_service_stream_does_not_miss_publish_during_snapshot_yield(
    tmp_path: Path,
) -> None:
    # 観点: snapshotのyield中にpublishと終端が起きても最新全文を送ること。
    # 目的: revisionを送信済みとして早取りし、最後の更新をdone前に失わない。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())
    job = service.jobs.get_or_create(message_id)
    job.status = ResponseJobStatus.STREAMING
    job.publish(StreamEvent("delta", delta="first"))
    with database.connect() as conn:
        message = MessageRepository(conn).get(message_id)

    async def interrupt_stream() -> list[StreamEvent]:
        stream = service.stream_events(message)
        events = [await anext(stream), await anext(stream)]
        job.publish(StreamEvent("delta", delta=" second"))
        job.status = ResponseJobStatus.COMPLETED
        job.close()
        async for event in stream:
            events.append(event)
        return events

    events = asyncio.run(interrupt_stream())

    assert events == [
        StreamEvent("status", message_id=message_id, status="streaming"),
        StreamEvent("full", message_id=message_id, content="first"),
        StreamEvent("full", message_id=message_id, content="first second"),
        StreamEvent("done", message_id=message_id),
    ]


def test_response_service_stream_replays_persisted_failed_message(
    tmp_path: Path,
) -> None:
    # 観点: メモリ上jobがないfailed messageでもSSEイベント列を復元できること。
    # 目的: 再起動後にprocessingをfailedへ収束する方針でも画面が終端できることを固定する。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())
    with database.connect() as conn:
        repo = MessageRepository(conn)
        message = update_message(
            conn,
            repo.get(message_id),
            content="partial",
            status=MessageStatus.FAILED,
        )
        conn.commit()

    events = asyncio.run(_collect_stream(service, message))

    assert events == [
        StreamEvent("full", message_id=message_id, content="partial"),
        StreamEvent("error", message_id=message_id, error="failed"),
        StreamEvent("done", message_id=message_id),
    ]


def test_response_service_returns_waiting_when_processing_job_is_not_local(
    tmp_path: Path,
) -> None:
    # 観点: local Jobがないprocessing messageのSSEをserverが保持しないこと。
    # 目的: 別processの完了確認をEventSource再接続へ委ね、server側DB pollingをなくす。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())
    with database.connect() as conn:
        processing = MessageRepository(conn).get(message_id)

    async def collect_without_polling() -> list[StreamEvent]:
        return await asyncio.wait_for(
            _collect_stream(service, processing),
            timeout=0.1,
        )

    events = asyncio.run(collect_without_polling())

    assert events == [
        StreamEvent("status", message_id=message_id, status="waiting"),
    ]
    assert service.jobs.get(message_id) is None


def test_response_service_stream_replays_persisted_reasoning_kind(
    tmp_path: Path,
) -> None:
    # 観点: メモリ上jobがないcompleted messageでもreasoningをSSE復元できること。
    # 目的: プロセス再起動後の画面がDBを真実として同じ表示を再構築できることを固定する。
    database, message_id = _database_with_assistant_message(tmp_path)
    service = ResponseService(database=database, responder=SuccessfulResponder())
    with database.connect() as conn:
        repo = MessageRepository(conn)
        message = update_message(
            conn,
            repo.get(message_id),
            content="answer",
            status=MessageStatus.COMPLETED,
            kinds=[MessageKind(kind="reasoning", content="thinking")],
        )
        conn.commit()

    events = asyncio.run(_collect_stream(service, message))

    assert events == [
        StreamEvent("full", message_id=message_id, content="answer"),
        StreamEvent("reasoning", message_id=message_id, reasoning="thinking"),
        StreamEvent("done", message_id=message_id),
    ]


async def _collect_stream(
    service: ResponseService, message: Message
) -> list[StreamEvent]:
    return [event async for event in service.stream_events(message)]


def _database_with_assistant_message(tmp_path: Path) -> tuple[Database, int]:
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        thread = save_thread(conn, user.id, "title")
        assistant = save_assistant_placeholder(
            conn,
            thread.id,
            "default",
        )
        conn.commit()
    return database, assistant.id


def _assistant() -> ResolvedAssistant:
    return ResolvedAssistant(
        id="default",
        name="Default",
        description="",
        system_prompt="",
        user_prompts=[],
        api_mode="chat_completions",
        base_url=None,
        config={"model": "test-model"},
        max_history_messages=40,
    )


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


def save_assistant_placeholder(
    conn: sqlite3.Connection,
    thread_id: str,
    assistant_id: str | None = None,
) -> Message:
    now = utcnow()
    return MessageRepository(conn).save(
        Message(
            id=0,
            thread_id=thread_id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.PROCESSING,
            assistant_id=assistant_id,
            created_at=now,
            updated_at=now,
        )
    )


def update_message(
    conn: sqlite3.Connection,
    message: Message,
    *,
    content: str,
    status: MessageStatus,
    kinds: list[MessageKind] | None = None,
) -> Message:
    return MessageRepository(conn).update(
        replace(
            message,
            content=content,
            status=status,
            kinds=kinds or [],
            updated_at=utcnow(),
        )
    )
