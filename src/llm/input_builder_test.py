
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from src.llm.input_builder import build_llm_input
from src.models import (
    Attachment,
    Message,
    MessageKind,
    MessageRole,
    MessageStatus,
    ResolvedAssistant,
)


def test_llm_input_builder_ignores_attachments_when_assistant_disallows_upload(
    tmp_path: Path,
) -> None:
    # 観点: 現在のassistantが添付非対応なら、履歴内の添付をLLMへ送らないこと。
    # 目的: 会話途中でテキスト専用モデルへ切り替えたときの安全側の入力構築を固定する。
    attachment = _attachment(tmp_path, content_type="image/png", body=b"image")
    message = _message(attachment.id, content="look")

    messages = build_llm_input(
        tmp_path,
        history=[message],
        attachments_by_id={attachment.id: attachment},
        assistant=_assistant(allow_file_upload=False),
    )

    assert messages == [{"role": "user", "content": "look"}]


def test_llm_input_builder_sends_responses_image_by_mime_type(
    tmp_path: Path,
) -> None:
    # 観点: 添付許可assistantでは画像MIMEをResponses APIのinput_imageへ変換すること。
    # 目的: 設定はallow_file_uploadへ一本化し、種類判定はMIME typeで行う契約を固定する。
    attachment = _attachment(tmp_path, content_type="image/png", body=b"image")
    message = _message(attachment.id, content="look")

    messages = build_llm_input(
        tmp_path,
        history=[message],
        attachments_by_id={attachment.id: attachment},
        assistant=_assistant(allow_file_upload=True, api_mode="responses"),
    )

    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "input_text", "text": "look"}
    assert content[1]["type"] == "input_image"
    assert str(content[1]["image_url"]).startswith("data:image/png;base64,")


def test_llm_input_builder_sends_responses_pdf_by_mime_type(
    tmp_path: Path,
) -> None:
    # 観点: PDF MIMEはResponses APIのinput_fileへ変換すること。
    # 目的: 画像/ファイル別の許可フラグを増やさず、MIME type分岐で処理する。
    attachment = _attachment(
        tmp_path,
        content_type="application/pdf",
        body=b"%PDF-1.7",
        filename="report.pdf",
    )
    message = _message(attachment.id, content="read this")

    messages = build_llm_input(
        tmp_path,
        history=[message],
        attachments_by_id={attachment.id: attachment},
        assistant=_assistant(allow_file_upload=True, api_mode="responses"),
    )

    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "input_file"
    assert content[1]["filename"] == "report.pdf"
    assert content[1]["file_data"] == "data:application/pdf;base64,JVBERi0xLjc="


def test_llm_input_builder_sends_text_attachment_content(
    tmp_path: Path,
) -> None:
    # 観点: text/plain添付はファイル本文をLLM入力のテキストへ展開すること。
    # 目的: プレーンテキストをファイル名だけでなく会話文脈として読ませる。
    attachment = _attachment(
        tmp_path,
        content_type="text/plain",
        body="重要なメモ".encode(),
        filename="memo.txt",
    )
    message = _message(attachment.id, content="read")

    messages = build_llm_input(
        tmp_path,
        history=[message],
        attachments_by_id={attachment.id: attachment},
        assistant=_assistant(allow_file_upload=True, api_mode="chat_completions"),
    )

    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[1] == {
        "type": "text",
        "text": "[添付ファイル: memo.txt]\n重要なメモ",
    }


def test_llm_input_builder_sends_unsupported_attachment_as_base64_text(
    tmp_path: Path,
) -> None:
    # 観点: 未対応MIME添付でもbase64化した内容をLLM入力へ渡すこと。
    # 目的: 専用パートがないファイルも情報を失わずモデル側の解釈へ委ねる。
    attachment = _attachment(
        tmp_path,
        content_type="application/octet-stream",
        body=b"\x00\x01\x02",
        filename="data.bin",
    )
    message = _message(attachment.id, content="inspect")

    messages = build_llm_input(
        tmp_path,
        history=[message],
        attachments_by_id={attachment.id: attachment},
        assistant=_assistant(allow_file_upload=True, api_mode="responses"),
    )

    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[1] == {
        "type": "input_text",
        "text": (
            "[添付ファイル: data.bin (application/octet-stream, 3 bytes)]\n"
            "base64:\nAAEC"
        ),
    }


def test_build_llm_input_applies_assistant_prompts_and_skips_failed(
    tmp_path: Path,
) -> None:
    # 観点: アシスタントのsystem/user promptを履歴へ反映し、failedを除外すること。
    # 目的: LLM入力構築の責務をmodelではなく入力builderへ閉じ込める。
    now = datetime(2026, 5, 30, tzinfo=UTC)
    assistant = _assistant(allow_file_upload=False)
    assistant = ResolvedAssistant(
        id=assistant.id,
        name=assistant.name,
        description=assistant.description,
        system_prompt="You are helpful.",
        user_prompts=["Answer in Japanese.", "Be concise."],
        api_mode=assistant.api_mode,
        base_url=assistant.base_url,
        config=assistant.config,
        max_history_messages=10,
    )
    history = [
        Message(
            id=1,
            thread_id="thread",
            role=MessageRole.USER,
            content="hello",
            status=MessageStatus.COMPLETED,
            assistant_id="default",
            created_at=now,
            updated_at=now,
        ),
        Message(
            id=2,
            thread_id="thread",
            role=MessageRole.ASSISTANT,
            content="broken",
            status=MessageStatus.FAILED,
            assistant_id="default",
            created_at=now,
            updated_at=now,
        ),
        Message(
            id=3,
            thread_id="thread",
            role=MessageRole.ASSISTANT,
            content="hi",
            status=MessageStatus.COMPLETED,
            assistant_id="default",
            created_at=now,
            updated_at=now,
        ),
    ]

    assert build_llm_input(
        tmp_path,
        history=history,
        attachments_by_id={},
        assistant=assistant,
    ) == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Answer in Japanese.\n\nBe concise.\n\nhello"},
        {"role": "assistant", "content": "hi"},
    ]


def _attachment(
    tmp_path: Path,
    *,
    content_type: str,
    body: bytes,
    filename: str = "photo.png",
) -> Attachment:
    stored_path = filename
    (tmp_path / stored_path).write_bytes(body)
    return Attachment(
        id="attachment-1",
        user_id=1,
        original_filename=filename,
        stored_path=stored_path,
        content_type=content_type,
        size_bytes=len(body),
        sha256="sha",
        created_at=datetime(2026, 5, 30, tzinfo=UTC),
    )


def _message(attachment_id: str, *, content: str) -> Message:
    now = datetime(2026, 5, 30, tzinfo=UTC)
    return Message(
        id=1,
        thread_id="thread",
        role=MessageRole.USER,
        content=content,
        status=MessageStatus.COMPLETED,
        assistant_id="default",
        created_at=now,
        updated_at=now,
        kinds=[MessageKind(kind="file", content=attachment_id)],
    )


def _assistant(
    *,
    allow_file_upload: bool,
    api_mode: str = "responses",
) -> ResolvedAssistant:
    return ResolvedAssistant(
        id="default",
        name="Default",
        description="",
        system_prompt="",
        user_prompts=[],
        api_mode=cast(Literal["responses", "chat_completions"], api_mode),
        base_url=None,
        config={"model": "test-model", "allow_file_upload": allow_file_upload},
        max_history_messages=40,
    )
