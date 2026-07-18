"""chat ユースケース間で共有する補助処理を定義する。"""

import json
from dataclasses import dataclass, replace
from uuid import uuid4

from ...infrastructure import (
    AttachmentRepository,
    MessageRepository,
    ThreadRepository,
    utcnow,
)
from ...llm.input_builder import build_llm_input
from ...models import (
    Attachment,
    Message,
    MessageKind,
    MessageRole,
    MessageStatus,
    PendingUpload,
    Thread,
    normalize_chat_input,
)
from ..assistant import AssistantUsecaseContext, resolve_runtime_assistant
from . import ChatUsecaseContext
from .save_message_attachments import save_message_attachments


@dataclass(frozen=True)
class ChatMutationResult:
    """チャット更新操作の結果を表す。"""

    thread: Thread
    user_message: Message
    assistant_message: Message


def create_chat_messages(
    *,
    user_id: int,
    thread_id: str,
    content: str,
    assistant_id: str,
    attachments: list[Attachment],
) -> tuple[Message, Message]:
    """ユーザー発言と assistant placeholder を構築する。"""
    now = utcnow()
    user_message = Message(
        id=0,
        thread_id=thread_id,
        role=MessageRole.USER,
        content=content,
        status=MessageStatus.COMPLETED,
        assistant_id=assistant_id,
        created_at=now,
        updated_at=now,
        kinds=file_kinds(attachments) or [],
    )
    assistant_message = Message(
        id=0,
        thread_id=thread_id,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.PROCESSING,
        assistant_id=assistant_id,
        created_at=now,
        updated_at=now,
    )
    return user_message, assistant_message


def start_response(
    context: ChatUsecaseContext,
    *,
    user_id: int,
    assistant_message: Message,
    history: list[Message],
) -> None:
    """assistant placeholderの応答を開始し、開始失敗時はfailedへ収束する。

    Args:
        context: チャット操作と応答開始に使う依存。
        user_id: 応答を開始するユーザーID。
        assistant_message: commit済みのassistant placeholder。
        history: Provider入力へ変換するmessage履歴。

    Returns:
        None。

    placeholderはこの関数より前にcommit済みである。入力構築やJob登録が失敗しても
    `processing`だけを残さず、ユーザーが再送・削除できるterminal状態へ変換する。
    SSE GETは生成開始点にしないため、通常リクエスト内ではここで即時回収する。
    """
    try:
        attachment_ids = [
            kind.content
            for message in history
            for kind in message.kinds
            if kind.kind == "file"
        ]
        with context.database.connect() as conn:
            assistant = resolve_runtime_assistant(
                user_id=user_id,
                assistant_id=assistant_message.assistant_id or "",
                context=_assistant_context(context),
            )
            attachments = AttachmentRepository(conn).list_by_ids_for_user(
                attachment_ids=attachment_ids,
                user_id=user_id,
            )
        attachments_by_id = {attachment.id: attachment for attachment in attachments}
        context.response_service.start_response(
            message_id=assistant_message.id,
            messages=build_llm_input(
                context.uploads_dir,
                history=history,
                attachments_by_id=attachments_by_id,
                assistant=assistant,
            ),
            assistant=assistant,
        )
    except Exception:
        # commit済みplaceholderの補償は元transactionへ戻れないため、
        # 新しいconnectionから条件付きでfailedへ収束させる。既にcancel等が
        # terminalへ確定していればRepositoryがその勝者を維持する。
        with context.database.connect() as conn:
            repo = MessageRepository(conn)
            current = repo.get(assistant_message.id)
            repo.update_processing_to_terminal(
                replace(
                    current,
                    status=MessageStatus.FAILED,
                    updated_at=utcnow(),
                )
            )
            conn.commit()
        raise


def file_kinds(attachments: list[Attachment]) -> list[MessageKind] | None:
    """添付一覧から message kind 一覧を構築する。"""
    if not attachments:
        return None
    return [
        MessageKind(
            kind="file",
            content=attachment.id,
            metadata_json=json.dumps(
                {
                    "filename": attachment.original_filename,
                    "content_type": attachment.content_type,
                    "size_bytes": attachment.size_bytes,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        for attachment in attachments
    ]


def normalize_thread_title(title: str) -> str:
    """Thread.title として保存する表示名を正規化する。"""
    return title.strip()[:80] or "New chat"


async def create_thread_mutation(
    context: ChatUsecaseContext,
    *,
    user_id: int,
    content: str,
    assistant_id: str | None,
    attachments: list[Attachment],
    uploads: list[PendingUpload],
) -> ChatMutationResult:
    """新規チャット保存と応答開始の共通処理を実行する。"""
    selected = resolve_runtime_assistant(
        user_id=user_id,
        assistant_id=assistant_id or "",
        context=_assistant_context(context),
    )
    with context.database.connect() as conn:
        uploaded_attachments: list[Attachment] = []
        try:
            uploaded_attachments = await save_message_attachments(
                user_id=user_id,
                assistant_id=selected.id,
                uploads=uploads,
                conn=conn,
                context=context,
            )
            saved_attachments = [*attachments, *uploaded_attachments]
            text = normalize_chat_input(content, len(saved_attachments))
            threads = ThreadRepository(conn)
            messages = MessageRepository(conn)
            title = (
                text or saved_attachments[0].original_filename
                if saved_attachments
                else text
            )
            now = utcnow()
            thread = threads.save(
                Thread(
                    id=str(uuid4()),
                    user_id=user_id,
                    title=normalize_thread_title(title),
                    created_at=now,
                    updated_at=now,
                )
            )
            user_message, assistant_message = create_chat_messages(
                user_id=user_id,
                thread_id=thread.id,
                content=text,
                assistant_id=selected.id,
                attachments=saved_attachments,
            )
            saved_user = messages.save(user_message)
            saved_assistant = messages.save(assistant_message)
            threads.touch(thread.id)
            history = messages.list_by_thread(thread.id)
            conn.commit()
        except BaseException:
            # DB rollbackでは保存済みファイル実体を戻せないため、commit前の失敗を補償する。
            _delete_uploaded_attachments(context, uploaded_attachments)
            raise
    start_response(
        context,
        user_id=user_id,
        assistant_message=saved_assistant,
        history=history,
    )
    return ChatMutationResult(
        thread=thread,
        user_message=saved_user,
        assistant_message=saved_assistant,
    )


async def append_thread_mutation(
    context: ChatUsecaseContext,
    *,
    user_id: int,
    thread_id: str,
    content: str,
    assistant_id: str | None,
    attachments: list[Attachment],
    uploads: list[PendingUpload],
) -> ChatMutationResult | None:
    """既存スレッドへの投稿保存と応答開始を実行する。"""
    selected = resolve_runtime_assistant(
        user_id=user_id,
        assistant_id=assistant_id or "",
        context=_assistant_context(context),
    )
    with context.database.connect() as conn:
        threads = ThreadRepository(conn)
        messages = MessageRepository(conn)
        # 存在しない投稿先のためにファイル実体を作らないよう、添付保存より先に確認する。
        thread = threads.get(thread_id, user_id)
        if thread is None:
            return None

        uploaded_attachments: list[Attachment] = []
        try:
            uploaded_attachments = await save_message_attachments(
                user_id=user_id,
                assistant_id=selected.id,
                uploads=uploads,
                conn=conn,
                context=context,
            )
            saved_attachments = [*attachments, *uploaded_attachments]
            text = normalize_chat_input(content, len(saved_attachments))
            user_message, assistant_message = create_chat_messages(
                user_id=user_id,
                thread_id=thread_id,
                content=text,
                assistant_id=selected.id,
                attachments=saved_attachments,
            )
            saved_user = messages.save(user_message)
            saved_assistant = messages.save(assistant_message)
            threads.touch(thread_id)
            history = messages.list_by_thread(thread_id)
            conn.commit()
        except BaseException:
            # transaction失敗時も実ファイルは残るため、新規アップロードだけを削除する。
            _delete_uploaded_attachments(context, uploaded_attachments)
            raise
    start_response(
        context,
        user_id=user_id,
        assistant_message=saved_assistant,
        history=history,
    )
    return ChatMutationResult(
        thread=thread,
        user_message=saved_user,
        assistant_message=saved_assistant,
    )


def _assistant_context(context: ChatUsecaseContext) -> AssistantUsecaseContext:
    """chat context から assistant 解決に必要な依存だけを取り出す。"""
    return AssistantUsecaseContext(
        database=context.database,
        load_connection_providers=context.load_connection_providers,
    )


def _delete_uploaded_attachments(
    context: ChatUsecaseContext,
    attachments: list[Attachment],
) -> None:
    """commit前に失敗した投稿で新規保存した添付ファイル実体を削除する。

    Args:
        context: 添付ファイル実体の保存境界を持つチャットユースケース依存。
        attachments: 今回の投稿でアップロードから新規保存した添付一覧。

    Returns:
        None。

    既存添付を誤って削除せず、DB transaction外の副作用だけを補償するため。
    """
    for attachment in attachments:
        context.attachment_storage.delete(attachment.stored_path)
