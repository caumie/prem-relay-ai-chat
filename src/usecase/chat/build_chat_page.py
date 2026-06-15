"""チャット画面表示に必要な読み取りユースケースを担当する。"""

from dataclasses import dataclass

from ...infrastructure import AttachmentRepository, ChatThreadQuery
from ...models import AssistantOption, Attachment, Message, MessageStatus, Thread
from ..assistant import AssistantUsecaseContext, list_available_assistants
from . import ChatUsecaseContext, chat_usecase_context


@dataclass(frozen=True)
class ChatPage:
    """チャット画面テンプレートへ渡す表示状態を表す。"""

    thread: Thread | None
    threads: list[Thread]
    messages: list[Message]
    attachments_by_id: dict[str, Attachment]
    assistants: list[AssistantOption]
    assistant_upload_permissions: dict[str, bool]
    assistant_allowed_file_extensions: dict[str, list[str]]
    assistant_names_by_id: dict[str, str]
    selected_assistant_id: str
    has_processing_message: bool


def build_chat_page(
    *,
    user_id: int,
    thread_id: str | None = None,
    context: ChatUsecaseContext | None = None,
) -> ChatPage | None:
    """チャット画面の表示状態をDBから構築する。

    Args:
        user_id: 表示するユーザーID。
        thread_id: 表示対象Thread ID。Noneなら未選択画面。

    Returns:
        表示状態。thread_id指定時に対象がなければNone。

    routeがRepository束や画面用Queryの組み合わせを知らずに済むよう、
    サイドバー、メッセージ、添付、assistant選択状態をここへ集約する。
    """
    ctx = context if context is not None else chat_usecase_context()
    assistants = list_available_assistants(
        user_id=user_id,
        context=_assistant_context(ctx),
    )
    with ctx.database.connect() as conn:
        query = ChatThreadQuery(conn)
        threads = query.list_sidebar_threads(user_id)
        detail = (
            query.get_detail_for_user(thread_id=thread_id, user_id=user_id)
            if thread_id is not None
            else None
        )
        if thread_id is not None and detail is None:
            return None
        thread = detail.thread if detail is not None else None
        messages = detail.messages if detail is not None else []
        attachments = AttachmentRepository(conn).list_by_ids_for_user(
            attachment_ids=_attachment_ids(messages),
            user_id=user_id,
        )
    assistant_names_by_id = {assistant.id: assistant.name for assistant in assistants}
    selected = _selected_assistant_id(
        messages=messages,
        assistants=assistants,
    )
    return ChatPage(
        thread=thread,
        threads=threads,
        messages=messages,
        attachments_by_id={attachment.id: attachment for attachment in attachments},
        assistants=assistants,
        assistant_upload_permissions={
            assistant.id: assistant.allow_file_upload for assistant in assistants
        },
        assistant_allowed_file_extensions={
            assistant.id: assistant.allowed_file_extensions for assistant in assistants
        },
        assistant_names_by_id=assistant_names_by_id,
        selected_assistant_id=selected,
        has_processing_message=any(
            message.status is MessageStatus.PROCESSING for message in messages
        ),
    )


def _attachment_ids(messages: list[Message]) -> list[str]:
    """メッセージ群に紐づく添付ID一覧を返す。"""
    return [
        kind.content
        for message in messages
        for kind in message.kinds
        if kind.kind == "file"
    ]


def _selected_assistant_id(
    *,
    messages: list[Message],
    assistants: list[AssistantOption],
) -> str:
    """表示中スレッドで選択状態にするassistant IDを返す。"""
    selected = assistants[0].id if assistants else ""
    available_ids = {assistant.id for assistant in assistants}
    for message in reversed(messages):
        if message.assistant_id in available_ids:
            return message.assistant_id or ""
    return selected


def _assistant_context(context: ChatUsecaseContext) -> AssistantUsecaseContext:
    """chat context から assistant 一覧取得に必要な依存だけを取り出す。"""
    return AssistantUsecaseContext(
        database=context.database,
        load_connection_providers=context.load_connection_providers,
    )
