"""chat 画面と SSE の HTML router を担当する。"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..infrastructure import AttachmentStorage
from ..models import Message, PendingUpload, User, UserInputError
from ..service.response_service import ResponseService
from ..usecase.context import UsecaseContext
from ..usecase.chat import (
    ChatPage,
    ChatUsecaseError,
    add_message as add_message_usecase,
    build_chat_page,
    cancel_response as cancel_response_usecase,
    create_chat as create_chat_usecase,
    delete_thread as delete_thread_usecase,
    get_attachment as get_attachment_usecase,
    prepare_response_stream,
    rename_thread as rename_thread_usecase,
)
from .util.csrf import ensure_csrf_token, verify_csrf_token

logger = logging.getLogger(__name__)


router = APIRouter()
templates: Jinja2Templates | None = None
_current_user: Callable[[Request], Awaitable[User]] | None = None
_response_service: ResponseService | None = None
_attachment_storage: AttachmentStorage | None = None
_usecase_context: UsecaseContext | None = None


def configure_chat_routes(
    *,
    usecase_context: UsecaseContext,
    current_user: Callable[[Request], Awaitable[User]],
    response_service: ResponseService,
    attachment_storage: AttachmentStorage,
) -> None:
    """chat router で使う依存関係を設定する。"""
    global _current_user, _usecase_context
    global _response_service, _attachment_storage
    _usecase_context = usecase_context
    _current_user = current_user
    _response_service = response_service
    _attachment_storage = attachment_storage


async def _current_user_dependency(request: Request) -> User:
    """chat router 用の現在ユーザー依存関係を返す。"""
    if _current_user is None:
        raise RuntimeError("Chat current_user dependency is not configured")
    return await _current_user(request)


def _templates() -> Jinja2Templates:
    """chat router で利用するテンプレート設定を返す。"""
    if templates is None:
        raise RuntimeError("Chat templates are not configured")
    return templates


def _response_runtime() -> ResponseService:
    """chat router で利用する response service を返す。"""
    if _response_service is None:
        raise RuntimeError("Chat response service is not configured")
    return _response_service


def _storage() -> AttachmentStorage:
    """chat router で利用する attachment storage を返す。"""
    if _attachment_storage is None:
        raise RuntimeError("Chat attachment storage is not configured")
    return _attachment_storage


def _context() -> UsecaseContext:
    """chat router で利用するusecase contextを返す。"""
    if _usecase_context is None:
        raise RuntimeError("Chat usecase context is not configured")
    return _usecase_context


def _chat_context(request: Request, user: User, page: ChatPage) -> dict[str, object]:
    """chat 画面用テンプレート context を返す。"""
    return {
        "request": request,
        "user": user,
        "thread": page.thread,
        "threads": page.threads,
        "messages": page.messages,
        "has_processing_message": page.has_processing_message,
        "attachments_by_id": page.attachments_by_id,
        "assistants": page.assistants,
        "assistant_upload_permissions": page.assistant_upload_permissions,
        "assistant_allowed_file_extensions": page.assistant_allowed_file_extensions,
        "assistant_names_by_id": page.assistant_names_by_id,
        "selected_assistant_id": page.selected_assistant_id,
        "selected_file_accept": _file_accept(
            page.assistant_allowed_file_extensions.get(page.selected_assistant_id, [])
        ),
        "csrf_token": ensure_csrf_token(request),
    }


@router.get("/chat", response_class=HTMLResponse)
async def chat_home(
    request: Request,
    user: User = Depends(_current_user_dependency),
) -> Response:
    """最新スレッドか新規チャット画面へ遷移する。"""
    page = build_chat_page(_context(), user_id=user.id)
    if page is None:
        raise HTTPException(404)
    logger.info("route.chat_home user_id=%s thread_count=%s", user.id, len(page.threads))
    if page.threads:
        return RedirectResponse(f"/chat/{page.threads[0].id}", 303)
    return _templates().TemplateResponse(
        request,
        "chat.html",
        _chat_context(request, user, page),
    )


@router.get("/chat/new", response_class=HTMLResponse)
async def chat_new(
    request: Request,
    user: User = Depends(_current_user_dependency),
) -> HTMLResponse:
    """新規チャット画面を表示する。"""
    logger.info("route.chat_new user_id=%s", user.id)
    page = build_chat_page(_context(), user_id=user.id)
    if page is None:
        raise HTTPException(404)
    return _templates().TemplateResponse(
        request,
        "chat.html",
        _chat_context(request, user, page),
    )


@router.post("/chat/new", response_class=HTMLResponse)
async def create_chat(
    request: Request,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
    content: str = Form(""),
    assistant_id: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> HTMLResponse:
    """新規チャット投稿を処理する。"""
    text = content.strip()
    logger.debug(
        "route.chat_new_submit user_id=%s assistant_id=%s chars=%s preview=%s",
        user.id,
        assistant_id,
        len(text),
        text[:120],
    )
    try:
        result = await create_chat_usecase(
            _context(),
            user_id=user.id,
            content=content,
            assistant_id=assistant_id,
            uploads=_pending_uploads(files),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info(
        "chat.created thread_id=%s assistant_id=%s",
        result.thread.id,
        result.assistant_message.id,
    )
    page = build_chat_page(_context(), user_id=user.id, thread_id=result.thread.id)
    if page is None:
        raise HTTPException(404)
    headers = (
        {"HX-Push-Url": f"/chat/{result.thread.id}"}
        if request.headers.get("HX-Request")
        else None
    )
    return _templates().TemplateResponse(
        request,
        "chat_created.html",
        _chat_context(request, user, page),
        headers=headers,
    )


@router.get("/chat/{thread_id}", response_class=HTMLResponse)
async def chat_thread(
    request: Request,
    thread_id: str,
    user: User = Depends(_current_user_dependency),
) -> HTMLResponse:
    """既存スレッド画面を表示する。"""
    page = build_chat_page(_context(), user_id=user.id, thread_id=thread_id)
    if page is None:
        raise HTTPException(404)
    logger.info("route.chat_thread user_id=%s thread_id=%s", user.id, thread_id)
    return _templates().TemplateResponse(
        request,
        "chat.html",
        _chat_context(request, user, page),
    )


@router.get("/chat/{thread_id}/title/edit", response_class=HTMLResponse)
async def edit_chat_thread_title(
    request: Request,
    thread_id: str,
    user: User = Depends(_current_user_dependency),
) -> HTMLResponse:
    """スレッドタイトル編集用の HTMX 断片を返す。"""
    page = build_chat_page(_context(), user_id=user.id, thread_id=thread_id)
    if page is None:
        raise HTTPException(404)
    return _templates().TemplateResponse(
        request,
        "thread_title_edit.html",
        _chat_context(request, user, page),
    )


@router.post("/chat/{thread_id}/title", response_class=HTMLResponse)
async def update_chat_thread_title(
    request: Request,
    thread_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
    title: str = Form(""),
) -> HTMLResponse:
    """スレッドタイトル更新を処理する。"""
    try:
        thread = rename_thread_usecase(
            _context(),
            thread_id=thread_id,
            user_id=user.id,
            title=title,
        )
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    page = build_chat_page(_context(), user_id=user.id, thread_id=thread.id)
    if page is None:
        raise HTTPException(404)
    return _templates().TemplateResponse(
        request,
        "thread_title_updated.html",
        _chat_context(request, user, page),
    )


@router.post("/chat/{thread_id}/delete")
async def delete_chat_thread(
    thread_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
) -> Response:
    """対象スレッドを論理削除する。"""
    try:
        delete_thread_usecase(_context(), thread_id=thread_id, user_id=user.id)
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    logger.info("chat.deleted thread_id=%s user_id=%s", thread_id, user.id)
    return RedirectResponse("/chat", 303)


@router.post("/chat/{thread_id}/messages", response_class=HTMLResponse)
async def add_chat_message(
    request: Request,
    thread_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
    content: str = Form(""),
    assistant_id: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> HTMLResponse:
    """既存スレッドへの投稿を処理する。"""
    text = content.strip()
    logger.debug(
        "route.chat_message_submit user_id=%s thread_id=%s assistant_id=%s chars=%s preview=%s",
        user.id,
        thread_id,
        assistant_id,
        len(text),
        text[:120],
    )
    try:
        result = await add_message_usecase(
            _context(),
            user_id=user.id,
            thread_id=thread_id,
            content=content,
            assistant_id=assistant_id,
            uploads=_pending_uploads(files),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    logger.info(
        "chat.message_added thread_id=%s assistant_id=%s",
        thread_id,
        result.assistant_message.id,
    )
    page = build_chat_page(_context(), user_id=user.id, thread_id=thread_id)
    if page is None:
        raise HTTPException(404)
    messages = page.messages[-2:]
    return _templates().TemplateResponse(
        request,
        "message_items.html",
        {
            "request": request,
            "thread": page.thread,
            "messages": messages,
            "assistant_names_by_id": page.assistant_names_by_id,
            "attachments_by_id": _attachments_by_id(page=page, messages=messages),
            "csrf_token": ensure_csrf_token(request),
        },
    )


@router.post("/chat/{thread_id}/messages/{message_id}/cancel")
async def cancel_chat_response(
    thread_id: str,
    message_id: int,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(_current_user_dependency),
) -> Response:
    """生成中 assistant message の応答生成を中断する。"""
    try:
        await cancel_response_usecase(
            _context(),
            user_id=user.id,
            thread_id=thread_id,
            message_id=message_id,
        )
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    logger.info(
        "chat.response_cancelled thread_id=%s message_id=%s user_id=%s",
        thread_id,
        message_id,
        user.id,
    )
    return Response(status_code=204)


@router.get("/attachments/{attachment_id}", name="attachment_download")
async def attachment_download(
    attachment_id: str,
    user: User = Depends(_current_user_dependency),
) -> FileResponse:
    """所有者検証付きで添付ファイルを返す。"""
    attachment = get_attachment_usecase(
        _context(),
        attachment_id=attachment_id,
        user_id=user.id,
    )
    if attachment is None:
        raise HTTPException(404)
    path = _storage().resolve(attachment.stored_path)
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.original_filename,
    )


@router.get("/chat/{thread_id}/stream/{response_id}", name="stream_response")
async def stream_response(
    thread_id: str,
    response_id: int,
    user: User = Depends(_current_user_dependency),
) -> StreamingResponse:
    """assistant 応答の SSE stream を返す。"""
    try:
        response_message = prepare_response_stream(
            _context(),
            user_id=user.id,
            thread_id=thread_id,
            response_id=response_id,
        )
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    logger.info(
        "route.stream_open user_id=%s thread_id=%s response_id=%s status=%s",
        user.id,
        thread_id,
        response_id,
        response_message.status,
    )

    async def events() -> AsyncIterator[str]:
        async for event in _response_runtime().stream_events(response_message):
            yield event.to_sse()

    return StreamingResponse(events(), media_type="text/event-stream")


def _attachments_by_id(*, page: ChatPage, messages: list[Message]) -> dict[str, object]:
    """メッセージ群に紐づく添付を page から抜き出す。"""
    attachment_ids = {
        kind.content
        for message in messages
        for kind in message.kinds
        if kind.kind == "file"
    }
    return {
        attachment_id: attachment
        for attachment_id, attachment in page.attachments_by_id.items()
        if attachment_id in attachment_ids
    }


def _file_accept(extensions: list[str]) -> str:
    """HTML file input のaccept属性へ渡す拡張子指定を返す。

    Args:
        extensions: dotなし小文字の許可拡張子一覧。

    Returns:
        `.jpg,.png` のようなaccept属性値。
    """
    return ",".join(f".{extension}" for extension in extensions)


def _pending_uploads(files: list[UploadFile]) -> list[PendingUpload]:
    """FastAPI UploadFile をusecase入力境界へ変換する。"""
    return [
        PendingUpload(
            filename=file.filename or "",
            content_type=file.content_type or "",
            read=file.read,
            close=file.close,
        )
        for file in files
    ]
