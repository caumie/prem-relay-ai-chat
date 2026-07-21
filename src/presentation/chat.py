"""chat 画面と SSE の HTML router を担当する。"""

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse

from ..models import Message, PendingUpload, User, UserInputError
from ..usecase.chat import (
    ChatPage,
    ChatUsecaseError,
    add_message as add_message_usecase,
    build_chat_page,
    cancel_response as cancel_response_usecase,
    create_chat as create_chat_usecase,
    delete_thread as delete_thread_usecase,
    get_attachment_download,
    prepare_response_stream,
    rename_thread as rename_thread_usecase,
    stream_response_events,
)
from .context import current_user, presentation_templates
from .util.csrf import ensure_csrf_token, verify_csrf_token

logger = logging.getLogger(__name__)


router = APIRouter()


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
    user: User = Depends(current_user),
) -> Response:
    """最新スレッドか新規チャット画面へ遷移する。"""
    page = build_chat_page(user_id=user.id)
    if page is None:
        raise HTTPException(404)
    logger.debug("route.chat_home user_id=%s thread_count=%s", user.id, len(page.threads))
    if page.threads:
        return RedirectResponse(f"/chat/{page.threads[0].id}", 303)
    return presentation_templates().TemplateResponse(
        request,
        "chat.html",
        _chat_context(request, user, page),
    )


@router.get("/chat/new", response_class=HTMLResponse)
async def chat_new(
    request: Request,
    user: User = Depends(current_user),
) -> HTMLResponse:
    """新規チャット画面を表示する。"""
    logger.debug("route.chat_new user_id=%s", user.id)
    page = build_chat_page(user_id=user.id)
    if page is None:
        raise HTTPException(404)
    return presentation_templates().TemplateResponse(
        request,
        "chat.html",
        _chat_context(request, user, page),
    )


@router.post("/chat/new", response_class=HTMLResponse)
async def create_chat(
    request: Request,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(current_user),
    content: str = Form(""),
    assistant_id: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> HTMLResponse:
    """新規チャット投稿を処理する。"""
    text = content.strip()
    logger.debug(
        "chat.create.submit user_id=%s assistant_id=%s char_count=%s attachment_count=%s",
        user.id,
        assistant_id,
        len(text),
        len(files),
    )
    try:
        result = await create_chat_usecase(
            user_id=user.id,
            content=content,
            assistant_id=assistant_id,
            uploads=_pending_uploads(files),
        )
    except UserInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info(
        "chat.created thread_id=%s assistant_message_id=%s",
        result.thread.id,
        result.assistant_message.id,
    )
    page = build_chat_page(user_id=user.id, thread_id=result.thread.id)
    if page is None:
        raise HTTPException(404)
    headers = (
        {"HX-Push-Url": f"/chat/{result.thread.id}"}
        if request.headers.get("HX-Request")
        else None
    )
    return presentation_templates().TemplateResponse(
        request,
        "chat_created.html",
        _chat_context(request, user, page),
        headers=headers,
    )


@router.get("/chat/{thread_id}", response_class=HTMLResponse)
async def chat_thread(
    request: Request,
    thread_id: str,
    user: User = Depends(current_user),
) -> HTMLResponse:
    """既存スレッド画面を表示する。"""
    page = build_chat_page(user_id=user.id, thread_id=thread_id)
    if page is None:
        raise HTTPException(404)
    logger.debug("route.chat_thread user_id=%s thread_id=%s", user.id, thread_id)
    return presentation_templates().TemplateResponse(
        request,
        "chat.html",
        _chat_context(request, user, page),
    )


@router.get("/chat/{thread_id}/title/edit", response_class=HTMLResponse)
async def edit_chat_thread_title(
    request: Request,
    thread_id: str,
    user: User = Depends(current_user),
) -> HTMLResponse:
    """スレッドタイトル編集用の HTMX 断片を返す。"""
    page = build_chat_page(user_id=user.id, thread_id=thread_id)
    if page is None:
        raise HTTPException(404)
    return presentation_templates().TemplateResponse(
        request,
        "thread_title_edit.html",
        _chat_context(request, user, page),
    )


@router.post("/chat/{thread_id}/title", response_class=HTMLResponse)
async def update_chat_thread_title(
    request: Request,
    thread_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(current_user),
    title: str = Form(""),
) -> HTMLResponse:
    """スレッドタイトル更新を処理する。"""
    try:
        thread = rename_thread_usecase(
            thread_id=thread_id,
            user_id=user.id,
            title=title,
        )
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    page = build_chat_page(user_id=user.id, thread_id=thread.id)
    if page is None:
        raise HTTPException(404)
    return presentation_templates().TemplateResponse(
        request,
        "thread_title_updated.html",
        _chat_context(request, user, page),
    )


@router.post("/chat/{thread_id}/delete")
async def delete_chat_thread(
    thread_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(current_user),
) -> Response:
    """対象スレッドを論理削除する。"""
    try:
        delete_thread_usecase(thread_id=thread_id, user_id=user.id)
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    logger.info("chat.deleted thread_id=%s user_id=%s", thread_id, user.id)
    return RedirectResponse("/chat", 303)


@router.post("/chat/{thread_id}/messages", response_class=HTMLResponse)
async def add_chat_message(
    request: Request,
    thread_id: str,
    _: None = Depends(verify_csrf_token),
    user: User = Depends(current_user),
    content: str = Form(""),
    assistant_id: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> HTMLResponse:
    """既存スレッドへの投稿を処理する。"""
    text = content.strip()
    logger.debug(
        "chat.message.submit user_id=%s thread_id=%s assistant_id=%s char_count=%s attachment_count=%s",
        user.id,
        thread_id,
        assistant_id,
        len(text),
        len(files),
    )
    try:
        result = await add_message_usecase(
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
        "chat.message_added thread_id=%s assistant_message_id=%s",
        thread_id,
        result.assistant_message.id,
    )
    page = build_chat_page(user_id=user.id, thread_id=thread_id)
    if page is None:
        raise HTTPException(404)
    messages = page.messages[-2:]
    return presentation_templates().TemplateResponse(
        request,
        "message_list.html",
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
    user: User = Depends(current_user),
) -> Response:
    """生成中 assistant message の応答生成を中断する。"""
    try:
        await cancel_response_usecase(
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
    user: User = Depends(current_user),
) -> FileResponse:
    """所有者検証付きで添付ファイルを返す。"""
    download = get_attachment_download(
        attachment_id=attachment_id,
        user_id=user.id,
    )
    if download is None:
        raise HTTPException(404)
    return FileResponse(
        download.path,
        media_type=download.media_type,
        filename=download.filename,
    )


@router.get("/chat/{thread_id}/stream/{response_id}", name="stream_response")
async def stream_response(
    thread_id: str,
    response_id: int,
    user: User = Depends(current_user),
) -> StreamingResponse:
    """assistant応答を観測するSSEを返し、生成開始は行わない。

    local Jobがないprocessing応答は短いwaiting streamとして終了する。
    ブラウザのEventSource再接続が次の所有者検証とDB確認を起動する。
    """
    try:
        response_message = prepare_response_stream(
            user_id=user.id,
            thread_id=thread_id,
            response_id=response_id,
        )
    except ChatUsecaseError as exc:
        raise HTTPException(404) from exc
    logger.debug(
        "route.stream_open user_id=%s thread_id=%s response_id=%s status=%s",
        user.id,
        thread_id,
        response_id,
        response_message.status,
    )

    async def events() -> AsyncIterator[str]:
        async for event in stream_response_events(response_message=response_message):
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
