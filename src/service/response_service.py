"""AI応答生成ジョブとSSEイベント生成を担当する。

このファイルは、メモリ上の応答ジョブ、LLM responder の実行、assistant
messageの完了/失敗更新、SSE向けイベント列の復元を扱う。FastAPIの
Request/Responseやテンプレート描画は扱わない。
"""

import asyncio
import json
import logging
import sqlite3
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field, replace
from enum import StrEnum
from time import perf_counter
from typing import Literal, Protocol

from ..models import LlmMessage, Message, MessageKind, MessageStatus, ResolvedAssistant
from ..infrastructure import Database, MessageRepository, utcnow

logger = logging.getLogger(__name__)


def _log_safe_exception(message: str, exception: BaseException, *args: object) -> None:
    """例外メッセージを出さず、原因スタックだけをERRORへ記録する。"""
    sanitized_exception = RuntimeError(type(exception).__name__)
    logger.error(
        message,
        *args,
        exc_info=(
            RuntimeError,
            sanitized_exception,
            exception.__traceback__,
        ),
    )


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


@dataclass(frozen=True)
class ResponseJobSnapshot:
    """一度の同期読取で確定した、購読者向けJob snapshotを表す。

    SSEのyield中にもProvider Taskは進むため、各fieldをyieldの都度読むと
    revisionと本文が異なる時点の値になる。この型へまとめてから送信することで、
    送信後の再比較による取りこぼし検出を可能にする。
    """

    revision: int
    status: ResponseJobStatus
    content: str
    reasoning: str
    error: str


def _empty_subscribers() -> set[asyncio.Event]:
    """ResponseJob.subscribers用に型付きの空setを返す。

    Returns:
        新しい購読通知Eventのset。
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
        subscribers: SSE接続ごとの更新通知Event。
    """

    message_id: int
    status: ResponseJobStatus = ResponseJobStatus.QUEUED
    content_buffer: str = ""
    reasoning_buffer: str = ""
    error: str = ""
    cancel_requested: bool = False
    task: asyncio.Task[None] | None = None
    revision: int = 0
    subscribers: set[asyncio.Event] = field(default_factory=_empty_subscribers)

    def subscribe(self) -> asyncio.Event:
        """ジョブの更新を購読するEventを作成する。

        Returns:
            この購読者専用の通知Event。

        Eventはデータを保持せず「snapshotが変化した」というwakeだけに使う。
        そのため遅い購読者にもProvider event数に比例するbacklogが生じない。
        """
        event = asyncio.Event()
        self.subscribers.add(event)
        logger.debug(
            "response.job.subscribe message_id=%s subscriber_count=%s",
            self.message_id,
            len(self.subscribers),
        )
        return event

    def unsubscribe(self, event: asyncio.Event) -> None:
        """購読Eventをジョブから外す。

        Args:
            event: `subscribe()` で作成したEvent。

        Returns:
            None。
        """
        self.subscribers.discard(event)
        logger.debug(
            "response.job.unsubscribe message_id=%s subscriber_count=%s",
            self.message_id,
            len(self.subscribers),
        )

    def snapshot(self) -> ResponseJobSnapshot:
        """現在revisionと表示内容を一度に読み取って返す。"""
        return ResponseJobSnapshot(
            revision=self.revision,
            status=self.status,
            content=self.content_buffer,
            reasoning=self.reasoning_buffer,
            error=self.error,
        )

    def publish(self, event: StreamEvent) -> None:
        """生成イベントをkind別bufferへ反映し、全購読者へ更新を通知する。

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
        # Eventは複数回のsetを一つへcoalesceできる。購読者はrevisionを比較し、
        # wake回数ではなく最新snapshotを正として読む。
        self.revision += 1
        for subscriber in list(self.subscribers):
            subscriber.set()

    def close(self) -> None:
        """全購読者をwakeして終端snapshotを確認させる。

        Returns:
            None。
        """
        for subscriber in list(self.subscribers):
            subscriber.set()


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

    def __init__(
        self,
        *,
        database: Database,
        responder: Responder,
    ) -> None:
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
        task.add_done_callback(self._observe_background_task)

    def _observe_background_task(self, task: asyncio.Task[None]) -> None:
        """完了Taskを回収し、未取得例外として失われる前に結果を観測する。

        Args:
            task: `start_response()`が登録した生成Task。

        Returns:
            None。
        """
        self.background_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            _log_safe_exception(
                "response.job.unhandled_exception error_type=%s",
                exception,
                type(exception).__name__,
            )

    async def cancel_response(self, message_id: int) -> bool:
        """local応答生成Taskを止め、部分本文をfailedとして残す。

        Args:
            message_id: cancelするassistant message ID。

        Returns:
            このprocessがJobを所有して処理できればTrue、なければFalse。

        Jobはprocess-localなので、Falseはusecaseが条件付きDB fallbackを行う
        判定に使う。
        """
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
        await self._finalize_job(job, MessageStatus.FAILED, "cancelled")
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
        started_at = perf_counter()
        event_counts: Counter[str] = Counter()
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
                    event_counts[event.type] += 1
                    job.publish(
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
                # responderが連続yieldしてもcancel要求を処理する機会を
                # event loopへ返す。
                await asyncio.sleep(0)
            terminal_status = await self._finalize_job(job, MessageStatus.COMPLETED, "")
            # DBのterminal状態が正本であり、success側が競合に負けた場合は
            # completedとして記録しない。
            if terminal_status is not ResponseJobStatus.COMPLETED:
                logger.debug(
                    "response.job.terminal_conflict message_id=%s requested=completed actual=%s",
                    message_id,
                    terminal_status.value,
                )
                return
            logger.info(
                "response.job.completed message_id=%s result=success duration_ms=%s chars=%s reasoning_chars=%s",
                message_id,
                int((perf_counter() - started_at) * 1000),
                len(job.content_buffer),
                len(job.reasoning_buffer),
            )
            logger.debug(
                "response.job.event_counts message_id=%s event_counts=%s",
                message_id,
                dict(event_counts),
            )
        except asyncio.CancelledError:
            if not job.cancel_requested:
                # cancel_response経由でない停止は所有者側の制御として伝播し、
                # user cancelと誤認してDBをfailedへ確定しない。
                job.status = ResponseJobStatus.QUEUED
                raise
            terminal_status = await self._finalize_job(
                job, MessageStatus.FAILED, "cancelled"
            )
            if terminal_status is not ResponseJobStatus.FAILED:
                logger.debug(
                    "response.job.terminal_conflict message_id=%s requested=failed actual=%s",
                    message_id,
                    terminal_status.value,
                )
                return
            logger.info(
                "response.job.cancelled message_id=%s result=cancelled duration_ms=%s chars=%s reasoning_chars=%s",
                message_id,
                int((perf_counter() - started_at) * 1000),
                len(job.content_buffer),
                len(job.reasoning_buffer),
            )
            logger.debug(
                "response.job.event_counts message_id=%s event_counts=%s",
                message_id,
                dict(event_counts),
            )
        except Exception as exc:
            terminal_status = await self._finalize_job(
                job, MessageStatus.FAILED, type(exc).__name__
            )
            if terminal_status is not ResponseJobStatus.FAILED:
                logger.debug(
                    "response.job.terminal_conflict message_id=%s requested=failed actual=%s",
                    message_id,
                    terminal_status.value,
                )
                return
            _log_safe_exception(
                "response.job.failed message_id=%s result=failed duration_ms=%s error_type=%s chars=%s reasoning_chars=%s",
                exc,
                message_id,
                int((perf_counter() - started_at) * 1000),
                type(exc).__name__,
                len(job.content_buffer),
                len(job.reasoning_buffer),
            )
            logger.debug(
                "response.job.event_counts message_id=%s event_counts=%s",
                message_id,
                dict(event_counts),
            )
        finally:
            job.close()

    async def stream_events(self, message: Message) -> AsyncIterator[StreamEvent]:
        """messageに対応するSSEイベント列を返す。

        Args:
            message: stream対象のassistant message。

        Yields:
            status/full/reasoning/error/done の最新snapshotイベント。

        メモリ上jobが存在しない場合でも、DBに保存済みの本文と状態から
        画面が自然に終端できるイベント列を復元する。
        """
        job = self.jobs.get(message.id)
        if job is None:
            # SSE GETは観測専用であり、Jobを持たないworkerから生成を再開しない。
            # DBを一度だけ確認し、processingなら短い応答を閉じてEventSourceの
            # 標準再接続へ次の観測を委ねる。
            with self.database.connect() as conn:
                try:
                    latest = MessageRepository(conn).get(message.id)
                except KeyError:
                    yield StreamEvent(
                        "error", message_id=message.id, error="target_missing"
                    )
                    yield StreamEvent("done", message_id=message.id)
                    return
            if latest.status is MessageStatus.PROCESSING:
                yield StreamEvent("status", message_id=message.id, status="waiting")
                return
            if latest.content:
                yield StreamEvent("full", message_id=message.id, content=latest.content)
            reasoning = _reasoning_content(latest)
            if reasoning:
                yield StreamEvent(
                    "reasoning",
                    message_id=message.id,
                    reasoning=reasoning,
                )
            if latest.status is MessageStatus.FAILED:
                yield StreamEvent("error", message_id=message.id, error="failed")
            yield StreamEvent("done", message_id=message.id)
            return

        subscriber = job.subscribe()
        last_revision = -1
        sent_status = False
        try:
            while True:
                # snapshot取得前にclearする。直後にpublishされてもEventが再度setされ、
                # snapshot取得後からwait開始までの通知を失わない。
                subscriber.clear()
                snapshot = job.snapshot()
                if not sent_status:
                    yield StreamEvent(
                        "status",
                        message_id=message.id,
                        status=snapshot.status.value,
                    )
                    sent_status = True
                if snapshot.revision != last_revision:
                    if snapshot.content:
                        yield StreamEvent(
                            "full",
                            message_id=message.id,
                            content=snapshot.content,
                        )
                    if snapshot.reasoning:
                        yield StreamEvent(
                            "reasoning",
                            message_id=message.id,
                            reasoning=snapshot.reasoning,
                        )
                    last_revision = snapshot.revision
                if snapshot.status is ResponseJobStatus.COMPLETED:
                    yield StreamEvent("done", message_id=message.id)
                    self.jobs.remove(message.id)
                    return
                if snapshot.status is ResponseJobStatus.FAILED:
                    yield StreamEvent(
                        "error",
                        message_id=message.id,
                        error=snapshot.error or "failed",
                    )
                    yield StreamEvent("done", message_id=message.id)
                    self.jobs.remove(message.id)
                    return
                current = job.snapshot()
                # yield中に進んだ更新は、送信済みrevisionとして扱わず次のloopで
                # 最新全文を再送する。変化がない時だけEvent待機へ入る。
                if (
                    current.revision != snapshot.revision
                    or current.status is not snapshot.status
                ):
                    continue
                await subscriber.wait()
        finally:
            job.unsubscribe(subscriber)

    async def _finalize_job(
        self,
        job: ResponseJob,
        status: MessageStatus,
        error: str,
    ) -> ResponseJobStatus:
        """DB terminalを正本として生成Jobを一度だけ確定・回収する。

        Args:
            job: 確定するprocess-local Job。
            status: completedまたはfailedの要求状態。
            error: failed時にSSEへ返す理由。completed時は空文字列。

        Returns:
            条件付き更新の競合も含め、実際に確定したJob状態。

        DB更新の勝者でstatus/content/reasoningを揃え、接続中snapshotと
        再接続後の表示を一致させる。対象消失やSQLite失敗でもlocal TaskとJobを
        残さないため、メモリ上はfailedとして購読者をwakeして即時回収する。
        """
        persisted = False
        effective_status = status
        try:
            with self.database.connect() as conn:
                repo = MessageRepository(conn)
                current = repo.get(job.message_id)
                terminal = repo.update_processing_to_terminal(
                    replace(
                        current,
                        content=job.content_buffer,
                        status=status,
                        kinds=_reasoning_kinds(job.reasoning_buffer) or [],
                        updated_at=utcnow(),
                    )
                )
                if terminal is not None:
                    conn.commit()
                    # UPDATEに負けた場合もRepositoryはDB上の勝者を返す。
                    # statusだけでなく表示snapshotも勝者へ揃え、接続中の画面と
                    # 再接続後のDB表示を一致させる。
                    effective_status = terminal.status
                    terminal_reasoning = _reasoning_content(terminal)
                    if (
                        terminal.content != job.content_buffer
                        or terminal_reasoning != job.reasoning_buffer
                    ):
                        job.revision += 1
                    job.content_buffer = terminal.content
                    job.reasoning_buffer = terminal_reasoning
                    persisted = True
                else:
                    error = "target_missing"
        except KeyError:
            logger.debug("response.job.target_missing message_id=%s", job.message_id)
            error = "target_missing"
        except sqlite3.OperationalError as exc:
            _log_safe_exception(
                "response.job.finalize_failed message_id=%s",
                exc,
                job.message_id,
            )
            # TODO: 永続化失敗後にDBへ残るprocessingを再収束する回収経路は未実装。
            # ここではlocal TaskとJobだけを収束し、無制限に保持しない。
            error = "persistence_failed"
        if persisted and effective_status is MessageStatus.COMPLETED:
            job.status = ResponseJobStatus.COMPLETED
            job.error = ""
        else:
            job.status = ResponseJobStatus.FAILED
            job.error = error or "failed"
        # subscriberはJob参照を保持しているため、Storeから即時回収しても
        # wake後に最後のsnapshotを送れる。購読有無でJob寿命を変えない。
        job.close()
        self.jobs.remove(job.message_id)
        return job.status


def _task_is_running(task: asyncio.Task[None] | None) -> bool:
    """現在も進行可能なasyncio taskかどうかを返す。"""
    return task is not None and not task.done() and task.get_loop().is_running()
