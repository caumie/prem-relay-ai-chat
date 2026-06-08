
"""チャット履歴と添付ファイルからLLM API入力を構築する。

このファイルはLLM入力構築の処理単位であり、状態を持つbuilderクラスではなく
公開関数として履歴、添付、assistant設定を受け取る。
"""

import base64
from pathlib import Path

from ..models import (
    Attachment,
    LlmContentPart,
    LlmMessage,
    Message,
    MessageRole,
    MessageStatus,
    ResolvedAssistant,
)


def build_llm_input(
    uploads_dir: Path,
    *,
    history: list[Message],
    attachments_by_id: dict[str, Attachment],
    assistant: ResolvedAssistant,
) -> list[LlmMessage]:
    """履歴からOpenAI互換APIへ渡すmessage列を作る。

    Args:
        uploads_dir: 添付保存ルート。保存済み相対パスの安全確認に使う。
        history: DBから作成順で読み込んだスレッド内メッセージ。
        attachments_by_id: message kindのfile参照から引ける添付一覧。
        assistant: 履歴件数、prompt、添付可否、API modeを持つ実行Assistant。

    Returns:
        OpenAI互換APIへ渡すrole/content辞書の配列。
    """
    selected = history[-assistant.max_history_messages :]
    messages: list[LlmMessage] = []
    if assistant.system_prompt:
        messages.append({"role": "system", "content": assistant.system_prompt})
    for item in selected:
        if item.status is MessageStatus.FAILED:
            continue
        content = item.content
        if item.role is MessageRole.USER and assistant.user_prompts:
            prompt = "\n\n".join(assistant.user_prompts)
            content = f"{prompt}\n\n{content}"
        messages.append(
            {
                "role": item.role.to_llm_role(),
                "content": _content_for_message(
                    uploads_dir,
                    message=item,
                    text=content,
                    attachments_by_id=attachments_by_id,
                    assistant=assistant,
                ),
            }
        )
    return messages


def _content_for_message(
    uploads_dir: Path,
    *,
    message: Message,
    text: str,
    attachments_by_id: dict[str, Attachment],
    assistant: ResolvedAssistant,
) -> str | list[LlmContentPart]:
    """1件のMessageをLLM contentへ変換する。"""
    attachments = [
        attachments_by_id[kind.content]
        for kind in message.kinds
        if kind.kind == "file" and kind.content in attachments_by_id
    ]
    if (
        message.role is not MessageRole.USER
        or not attachments
        or not bool(assistant.config.get("allow_file_upload", False))
    ):
        return text
    if assistant.api_mode == "chat_completions":
        return _chat_completions_content(uploads_dir, text=text, attachments=attachments)
    return _responses_content(uploads_dir, text=text, attachments=attachments)


def _responses_content(
    uploads_dir: Path, *, text: str, attachments: list[Attachment]
) -> list[LlmContentPart]:
    """Responses API向けのcontent partsへ添付を変換する。"""
    parts: list[LlmContentPart] = []
    if text:
        parts.append({"type": "input_text", "text": text})
    for attachment in attachments:
        encoded = _encoded_file(uploads_dir, attachment)
        if attachment.content_type.startswith("image/"):
            parts.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{attachment.content_type};base64,{encoded}",
                }
            )
        elif attachment.content_type == "application/pdf":
            parts.append(
                {
                    "type": "input_file",
                    "filename": attachment.original_filename,
                    "file_data": encoded,
                }
            )
        elif _is_text_attachment(attachment):
            parts.append(
                {
                    "type": "input_text",
                    "text": _decoded_text_attachment(uploads_dir, attachment),
                }
            )
        else:
            parts.append(
                {
                    "type": "input_text",
                    "text": _base64_attachment_text(
                        attachment=attachment,
                        encoded=encoded,
                    ),
                }
            )
    return parts or [{"type": "input_text", "text": ""}]


def _chat_completions_content(
    uploads_dir: Path, *, text: str, attachments: list[Attachment]
) -> str | list[LlmContentPart]:
    """Chat Completions API向けのcontent partsへ添付を変換する。"""
    parts: list[LlmContentPart] = []
    if text:
        parts.append({"type": "text", "text": text})
    notes: list[str] = []
    for attachment in attachments:
        if attachment.content_type.startswith("image/"):
            encoded = _encoded_file(uploads_dir, attachment)
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{attachment.content_type};base64,{encoded}"
                    },
                }
            )
        elif _is_text_attachment(attachment):
            parts.append(
                {
                    "type": "text",
                    "text": _decoded_text_attachment(uploads_dir, attachment),
                }
            )
        else:
            notes.append(
                _base64_attachment_text(
                    attachment=attachment,
                    encoded=_encoded_file(uploads_dir, attachment),
                )
            )
    if notes:
        parts.append({"type": "text", "text": "\n".join(notes)})
    if not parts:
        return text
    return parts


def _encoded_file(uploads_dir: Path, attachment: Attachment) -> str:
    """添付ファイルを安全な保存先配下から読み、base64文字列へ変換する。

    Args:
        uploads_dir: 添付保存ルート。
        attachment: DBに保存済みの添付ファイル情報。

    Returns:
        ファイル内容のbase64文字列。
    """
    path = (uploads_dir / attachment.stored_path).resolve()
    root = uploads_dir.resolve()
    if root != path and root not in path.parents:
        raise ValueError("invalid attachment path")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _decoded_text_attachment(uploads_dir: Path, attachment: Attachment) -> str:
    """テキスト添付をUTF-8本文として読み、LLM向け説明付き文字列へ変換する。

    Args:
        uploads_dir: 添付保存ルート。
        attachment: DBに保存済みのテキスト添付情報。

    Returns:
        ファイル名見出しと本文を含むテキスト。
    """
    path = (uploads_dir / attachment.stored_path).resolve()
    root = uploads_dir.resolve()
    if root != path and root not in path.parents:
        raise ValueError("invalid attachment path")
    body = path.read_text(encoding="utf-8", errors="replace")
    return f"[添付ファイル: {attachment.original_filename}]\n{body}"


def _is_text_attachment(attachment: Attachment) -> bool:
    """添付MIME typeが本文展開できるテキスト系か判定する。

    Args:
        attachment: 判定対象の添付情報。

    Returns:
        text/* またはJSON/XML系ならTrue。
    """
    content_type = attachment.content_type.split(";", 1)[0].lower()
    return (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml"}
        or content_type.endswith("+json")
        or content_type.endswith("+xml")
    )


def _attachment_note(attachment: Attachment) -> str:
    return (
        f"[添付ファイル: {attachment.original_filename} "
        f"({attachment.content_type}, {attachment.size_bytes} bytes)]"
    )


def _base64_attachment_text(*, attachment: Attachment, encoded: str) -> str:
    """未対応添付をbase64本文としてLLMへ渡す文字列を作る。

    Args:
        attachment: DBに保存済みの添付情報。
        encoded: ファイル内容のbase64文字列。

    Returns:
        添付メタ情報とbase64本文を含むテキスト。
    """
    return f"{_attachment_note(attachment)}\nbase64:\n{encoded}"
