"""chat ユースケース間で共有する補助処理を定義する。"""

import json
from dataclasses import dataclass
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
from ..assistant import resolve_runtime_assistant
from ..context import UsecaseContext
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
    context: UsecaseContext,
    *,
    user_id: int,
    assistant_message: Message,
    history: list[Message],
) -> None:
    """assistant placeholder に対応する応答生成を開始する。"""
    attachment_ids = [
        kind.content
        for message in history
        for kind in message.kinds
        if kind.kind == "file"
    ]
    with context.database.connect() as conn:
        assistant = resolve_runtime_assistant(
            context,
            user_id=user_id,
            assistant_id=assistant_message.assistant_id or "",
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
    context: UsecaseContext,
    *,
    user_id: int,
    content: str,
    assistant_id: str | None,
    attachments: list[Attachment],
    uploads: list[PendingUpload],
) -> ChatMutationResult:
    """新規チャット保存と応答開始の共通処理を実行する。"""
    selected = resolve_runtime_assistant(
        context,
        user_id=user_id,
        assistant_id=assistant_id or "",
    )
    with context.database.connect() as conn:
        saved_attachments = [
            *attachments,
            *await save_message_attachments(
                context,
                user_id=user_id,
                assistant_id=selected.id,
                uploads=uploads,
                conn=conn,
            ),
        ]
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
    context: UsecaseContext,
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
        context,
        user_id=user_id,
        assistant_id=assistant_id or "",
    )
    with context.database.connect() as conn:
        saved_attachments = [
            *attachments,
            *await save_message_attachments(
                context,
                user_id=user_id,
                assistant_id=selected.id,
                uploads=uploads,
                conn=conn,
            ),
        ]
        text = normalize_chat_input(content, len(saved_attachments))
        threads = ThreadRepository(conn)
        messages = MessageRepository(conn)
        thread = threads.get(thread_id, user_id)
        if thread is None:
            return None
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
