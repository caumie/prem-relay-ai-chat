"""AI応答生成ジョブとSSEイベント生成を担当する。

このファイルは、メモリ上の応答ジョブ、LLM responder の実行、assistant
messageの完了/失敗更新、SSE向けイベント列の復元を扱う。FastAPIの
Request/Responseやテンプレート描画は扱わない。
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Literal, Protocol

from ..models import LlmMessage, Message, MessageKind, MessageStatus, ResolvedAssistant
from ..infrastructure import Database, MessageRepository, utcnow

logger = logging.getLogger(__name__)


def _reasoning_kinds(reasoning: str) -> list[MessageKind] | None:
    if not reasoning:
        return None
    return [MessageKind(kind="reasoning", content=reasoning)]


def _reasoning_content(message: Message) -> str:
    return "".join(kind.content for kind in message.kinds if kind.kind == "reasoning")


@dataclass(frozen=True)
class StreamEvent:
    """SSEで画面へ送る応答生成イベントを表す。

    Attributes:
        type: status/full/delta/reasoning/reasoning_delta/done/error のイベント種別。
        message_id: 対象assistant messageのID。
        content: fullイベントで送る現在全文。
        delta: deltaイベントで送る追加本文。
        reasoning: reasoningイベントで送る現在のreasoning全文。
        reasoning_delta: reasoning_deltaイベントで送る追加reasoning。
        status: statusイベントで送るジョブ状態。
        error: errorイベントで送る失敗理由。
    """

    type: Literal[
        "status",
        "full",
        "delta",
        "reasoning",
        "reasoning_delta",
        "done",
        "error",
    ]
    message_id: int | str = ""
    content: str = ""
    delta: str = ""
    reasoning: str = ""
    reasoning_delta: str = ""
    status: str = ""
    error: str = ""

    def to_sse(self) -> str:
        """イベントをSSEのdata行へ変換する。

        Returns:
            `data: {...}\n\n` 形式のSSE文字列。

        空値はpayloadから省き、受信側がイベント種別に必要な値だけを
        読めるようにする。
        """
        payload = {
            key: value
            for key, value in self.__dict__.items()
            if value not in ("", None)
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"data: {body}\n\n"


class ResponseJobStatus(StrEnum):
    """メモリ上の応答生成ジョブ状態を表す。"""

    QUEUED = "queued"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"


def _empty_subscribers() -> set[asyncio.Queue[StreamEvent | None]]:
    """ResponseJob.subscribers用に型付きの空setを返す。

    Returns:
        新しい購読者Queueのset。
    """
    return set()


@dataclass
class ResponseJob:
    """1つのassistant messageに対応するメモリ上の生成状態を表す。

    Attributes:
        message_id: 対象assistant message ID。
        status: 現在のジョブ状態。
        content_buffer: これまでに生成された本文。
        reasoning_buffer: これまでに生成されたreasoning。
        error: 失敗理由。
        subscribers: SSE接続ごとのイベントQueue。
    """

    message_id: int
    status: ResponseJobStatus = ResponseJobStatus.QUEUED
    content_buffer: str = ""
    reasoning_buffer: str = ""
    error: str = ""
    cancel_requested: bool = False
    task: asyncio.Task[None] | None = None
    subscribers: set[asyncio.Queue[StreamEvent | None]] = field(
        default_factory=_empty_subscribers
    )

    def subscribe(self) -> asyncio.Queue[StreamEvent | None]:
        """ジョブのイベント購読Queueを作成する。

        Returns:
            この購読者専用のQueue。

        複数タブや再接続が同じ生成を追えるよう、購読者ごとにQueueを分ける。
        """
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[StreamEvent | None]) -> None:
        """購読Queueをジョブから外す。

        Args:
            queue: `subscribe()` で作成したQueue。

        Returns:
            None。
        """
        self.subscribers.discard(queue)

    async def publish(self, event: StreamEvent) -> None:
        """生成イベントをkind別bufferへ反映し、全購読者へ配信する。

        Args:
            event: responderまたはserviceが発行したStreamEvent。

        Returns:
            None。

        後から接続した画面へ現在全文を返せるよう、
        delta/fullとreasoning系イベントはそれぞれのbufferへ反映する。
        """
        if event.type == "delta":
            self.content_buffer += event.delta
        if event.type == "full":
            self.content_buffer = event.content
        if event.type == "reasoning_delta":
            self.reasoning_buffer += event.reasoning_delta
        if event.type == "reasoning":
            self.reasoning_buffer = event.reasoning
        for queue in list(self.subscribers):
            await queue.put(event)

    async def close(self) -> None:
        """全購読者へ終端を通知し、購読状態を破棄する。

        Returns:
            None。
        """
        for queue in list(self.subscribers):
            await queue.put(None)
        self.subscribers.clear()


class ResponseJobStore:
    """message_idをキーにメモリ上の応答生成ジョブを管理する。"""

    def __init__(self) -> None:
        self._jobs: dict[int, ResponseJob] = {}

    def get_or_create(self, message_id: int) -> ResponseJob:
        """対象message_idのジョブを取得し、なければ作成する。

        Args:
            message_id: assistant message ID。

        Returns:
            既存または新規のResponseJob。
        """
        job = self._jobs.get(message_id)
        if job is None:
            job = ResponseJob(message_id=message_id)
            self._jobs[message_id] = job
        return job

    def get(self, message_id: int) -> ResponseJob | None:
        """対象message_idのジョブを取得する。

        Args:
            message_id: assistant message ID。

        Returns:
            存在すればResponseJob、なければNone。
        """
        return self._jobs.get(message_id)

    def remove(self, message_id: int) -> None:
        """対象message_idのジョブを破棄する。

        Args:
            message_id: assistant message ID。

        Returns:
            None。
        """
        self._jobs.pop(message_id, None)


class Responder(Protocol):
    """LLM応答生成の外部境界を表すProtocol。"""

    def stream(
        self,
        *,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> AsyncIterator[StreamEvent]: ...


class ResponseService:
    """応答生成ジョブの開始、実行、SSEイベント復元をまとめる。"""

    def __init__(self, *, database: Database, responder: Responder) -> None:
        """ResponseServiceを作成する。

        Args:
            database: assistant messageを更新するDatabase。
            responder: LLM応答をStreamEventとして返す外部境界。

        Returns:
            None。
        """
        self.database = database
        self.responder = responder
        self.jobs = ResponseJobStore()
        self.background_tasks: set[asyncio.Task[None]] = set()

    def start_response(
        self,
        *,
        message_id: int,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> None:
        """応答生成をbackground taskとして開始する。

        Args:
            message_id: assistant placeholderのMessage ID。
            messages: LLMへ渡す履歴。
            assistant: 応答生成に使うAssistant。

        Returns:
            None。

        FastAPI routeがasyncio taskやジョブストアを直接扱わないよう、
        生成開始の副作用をこのserviceに閉じる。
        """
        job = self.jobs.get_or_create(message_id)
        if _task_is_running(job.task):
            logger.debug("response.job.already_started message_id=%s", message_id)
            return
        if job.status != ResponseJobStatus.QUEUED:
            logger.debug(
                "response.job.start_skipped message_id=%s status=%s",
                message_id,
                job.status,
            )
            return
        task = asyncio.create_task(
            self.run_response(
                message_id=message_id,
                messages=messages,
                assistant=assistant,
            )
        )
        job.task = task
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def cancel_response(self, message_id: int) -> bool:
        """実行中の応答生成taskを止め、部分本文をfailedとして残す。"""
        job = self.jobs.get(message_id)
        if job is None:
            return False
        job.cancel_requested = True
        job.error = "cancelled"
        task = job.task
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            return True
        self._fail_message(
            message_id=message_id,
            content=job.content_buffer,
            reasoning=job.reasoning_buffer,
        )
        job.status = ResponseJobStatus.FAILED
        await job.close()
        return True

    async def run_response(
        self,
        *,
        message_id: int,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> None:
        """LLM応答生成を実行し、進行状況と最終状態を反映する。

        Args:
            message_id: assistant placeholderのMessage ID。
            messages: LLMへ渡す履歴。
            assistant: 応答生成に使うAssistant。

        Returns:
            None。

        成功時はassistant messageをcompletedへ、失敗時はpartial contentを残して
        failedへ更新する。
        """
        job = self.jobs.get_or_create(message_id)
        if job.status != ResponseJobStatus.QUEUED:
            return
        job.status = ResponseJobStatus.STREAMING
        logger.debug("response.job.start message_id=%s", message_id)
        try:
            async for event in self.responder.stream(
                messages=messages,
                assistant=assistant,
            ):
                if event.type in {
                    "delta",
                    "full",
                    "reasoning",
                    "reasoning_delta",
                    "status",
                }:
                    await job.publish(
                        StreamEvent(
                            event.type,
                            message_id=message_id,
                            content=event.content,
                            delta=event.delta,
                            reasoning=event.reasoning,
                            reasoning_delta=event.reasoning_delta,
                            status=event.status,
                        )
                    )
                await asyncio.sleep(0)
            with self.database.connect() as conn:
                repo = MessageRepository(conn)
                message = repo.get(message_id)
                repo.update(
                    replace(
                        message,
                        content=job.content_buffer,
                        status=MessageStatus.COMPLETED,
                        kinds=_reasoning_kinds(job.reasoning_buffer) or [],
                        updated_at=utcnow(),
                    )
                )
                conn.commit()
            job.status = ResponseJobStatus.COMPLETED
            logger.info(
                "response.job.completed message_id=%s chars=%s content=%r reasoning=%r",
                message_id,
                len(job.content_buffer),
                job.content_buffer,
                job.reasoning_buffer,
            )
        except asyncio.CancelledError:
            if not job.cancel_requested:
                job.status = ResponseJobStatus.QUEUED
                raise
            self._fail_message(
                message_id=message_id,
                content=job.content_buffer,
                reasoning=job.reasoning_buffer,
            )
            job.status = ResponseJobStatus.FAILED
            job.error = "cancelled"
            logger.info(
                "response.job.cancelled message_id=%s chars=%s content=%r reasoning=%r",
                message_id,
                len(job.content_buffer),
                job.content_buffer,
                job.reasoning_buffer,
            )
        except Exception as exc:
            with self.database.connect() as conn:
                repo = MessageRepository(conn)
                message = repo.get(message_id)
                repo.update(
                    replace(
                        message,
                        content=job.content_buffer,
                        status=MessageStatus.FAILED,
                        kinds=_reasoning_kinds(job.reasoning_buffer) or [],
                        updated_at=utcnow(),
                    )
                )
                conn.commit()
            job.status = ResponseJobStatus.FAILED
            job.error = str(exc)
            logger.error(
                "response.job.failed message_id=%s error=%s content=%r reasoning=%r",
                message_id,
                exc,
                job.content_buffer,
                job.reasoning_buffer,
            )
        finally:
            await job.close()

    async def stream_events(self, message: Message) -> AsyncIterator[StreamEvent]:
        """messageに対応するSSEイベント列を返す。

        Args:
            message: stream対象のassistant message。

        Yields:
            status/full/delta/error/done のStreamEvent。

        メモリ上jobが存在しない場合でも、DBに保存済みの本文と状態から
        画面が自然に終端できるイベント列を復元する。
        """
        job = self.jobs.get(message.id)
        if job is None:
            if message.content:
                yield StreamEvent(
                    "full", message_id=message.id, content=message.content
                )
            reasoning = _reasoning_content(message)
            if reasoning:
                yield StreamEvent(
                    "reasoning",
                    message_id=message.id,
                    reasoning=reasoning,
                )
            if message.status is MessageStatus.FAILED:
                yield StreamEvent("error", message_id=message.id, error="failed")
            yield StreamEvent("done", message_id=message.id)
            return

        queue = job.subscribe()
        try:
            yield StreamEvent("status", message_id=message.id, status=job.status.value)
            if job.content_buffer:
                yield StreamEvent(
                    "full",
                    message_id=message.id,
                    content=job.content_buffer,
                )
            if job.reasoning_buffer:
                yield StreamEvent(
                    "reasoning",
                    message_id=message.id,
                    reasoning=job.reasoning_buffer,
                )
            if job.status == ResponseJobStatus.COMPLETED:
                yield StreamEvent("done", message_id=message.id)
                self.jobs.remove(message.id)
                return
            if job.status == ResponseJobStatus.FAILED:
                yield StreamEvent(
                    "error",
                    message_id=message.id,
                    error=job.error or "failed",
                )
                yield StreamEvent("done", message_id=message.id)
                self.jobs.remove(message.id)
                return
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            job.unsubscribe(queue)

        if job.error:
            yield StreamEvent(
                "error", message_id=message.id, error=job.error or "failed"
            )
        else:
            yield StreamEvent("done", message_id=message.id)
        self.jobs.remove(message.id)

    def _fail_message(self, *, message_id: int, content: str, reasoning: str) -> None:
        """部分本文とreasoningをfailed messageとして永続化する。"""
        with self.database.connect() as conn:
            repo = MessageRepository(conn)
            message = repo.get(message_id)
            repo.update(
                replace(
                    message,
                    content=content,
                    status=MessageStatus.FAILED,
                    kinds=_reasoning_kinds(reasoning) or [],
                    updated_at=utcnow(),
                )
            )
            conn.commit()


def _task_is_running(task: asyncio.Task[None] | None) -> bool:
    """現在も進行可能なasyncio taskかどうかを返す。"""
    return task is not None and not task.done() and task.get_loop().is_running()
