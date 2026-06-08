"""チャット応答SSE routeのHTTP境界を検証する。"""

import json
import re
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response as HttpResponse

from src.app import build_app
from src.config import AppConfig
from src.infrastructure import (
    AuthRepository,
    BaseAssistantRepository,
    MessageRepository,
    ThreadRepository,
)
from src.models import (
    AssistantGenerationConfig,
    BaseAssistant,
    LlmMessage,
    MessageRole,
)
from src.service.response_service import StreamEvent


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="hello")


def test_sse_stream_route_returns_event_stream_response(tmp_path: Path) -> None:
    # 観点: SSE routeが認証済みユーザーのprocessing messageへHTTP streamを返すこと。
    # 目的: 生成内容や永続化ではなく、presentation層のHTTP境界だけを固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    client = TestClient(app)
    _login(client)
    _post_new_chat(client, app)

    thread_id, assistant_id = _latest_assistant(app)
    response = client.get(f"/chat/{thread_id}/stream/{assistant_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: " in response.text


def save_base_assistant(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str,
    system_prompt: str,
    user_prompts: list[str],
    connection_provider_id: str,
    model: str,
    generation_config: AssistantGenerationConfig,
    max_history_messages: int,
    allow_file_upload: bool,
) -> BaseAssistant:
    return BaseAssistantRepository(conn).save(
        BaseAssistant(
            id=str(uuid4()),
            name=name,
            description=description,
            system_prompt=system_prompt,
            user_prompts=user_prompts,
            connection_provider_id=connection_provider_id,
            model=model,
            generation_config=generation_config,
            max_history_messages=max_history_messages,
            allow_file_upload=allow_file_upload,
        )
    )


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
    )


def _login(client: TestClient) -> HttpResponse:
    return client.post(
        "/login",
        data={
            "login_name": "admin",
            "password": "adminpass",
            "_csrf_token": _csrf_token(client.get("/login").text),
        },
        follow_redirects=False,
    )


def _post_new_chat(client: TestClient, app: FastAPI) -> HttpResponse:
    assistant_id = _ensure_default_assistant(app)
    page = client.get("/chat/new")
    return client.post(
        "/chat/new",
        data={
            "content": "hello",
            "assistant_id": assistant_id,
            "_csrf_token": _csrf_token(page.text),
        },
    )


def _latest_assistant(app: FastAPI) -> tuple[str, int]:
    database = app.state.database
    with database.connect() as conn:
        auth_repo = AuthRepository(conn)
        thread_repo = ThreadRepository(conn)
        message_repo = MessageRepository(conn)
        user = auth_repo.get_by_login_name("admin")
        assert user is not None
        thread = thread_repo.list_by_user(user.id)[0]
        assistant = [
            message
            for message in message_repo.list_by_thread(thread.id)
            if message.role is MessageRole.ASSISTANT
        ][0]
    return thread.id, assistant.id


def _ensure_default_assistant(app: FastAPI) -> str:
    config = app.state.config
    (config.data_dir / "connection_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "api_mode": "responses",
                        "api_key": "test",
                        "base_url": "https://api.openai.com/v1",
                        "allowed_models": ["gpt-5-mini"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with app.state.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")
        assert user is not None
        assistants = BaseAssistantRepository(conn)
        existing = assistants.list_active()
        if existing:
            conn.commit()
            return existing[0].id
        created = save_base_assistant(
            conn,
            name="Default",
            description="",
            system_prompt="",
            user_prompts=[],
            connection_provider_id="openai",
            model="gpt-5-mini",
            generation_config={},
            max_history_messages=40,
            allow_file_upload=False,
        )
        conn.commit()
        return created.id


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
