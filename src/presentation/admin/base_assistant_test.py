import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.presentation.test_support import (
    usecase_runtime_for,
    started_test_client,
)

from src.app import build_app
from src.config import AppConfig
from src.infrastructure import BaseAssistantRepository
from src.models import BaseAssistant, LlmMessage
from src.service.response_service import StreamEvent


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="ok")


def test_admin_base_assistant_create_route_redirects_and_lists_assistant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 管理者のBaseAssistant作成POSTがフォーム入力を受け取り一覧へ戻ること。
    # 目的: 作成usecaseの詳細ではなくHTTP入口の配線契約だけを固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    _write_provider_config(tmp_path)
    client = started_test_client(app)
    _login(client)
    new_page = client.get("/admin/base-assistants/new")

    response = client.post(
        "/admin/base-assistants/new",
        data={
            "name": "Ops",
            "description": "運用用",
            "system_prompt": "be helpful",
            "user_prompts": "base prompt",
            "connection_provider_id": "openai",
            "model": "gpt-5-mini",
            "max_history_messages": "20",
            "allow_file_upload": "on",
            "generation_config_json": '{"temperature": 0.2}',
            "_csrf_token": _csrf_token(new_page.text),
        },
        follow_redirects=False,
    )
    listed = client.get("/admin/base-assistants")

    assert response.status_code == 303
    assert "Ops" in listed.text
    assert "Allowed" in listed.text
    captured = capsys.readouterr()
    assert "audit.base_assistant.created" in captured.err


def test_admin_base_assistant_update_route_redirects_and_lists_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 管理者のBaseAssistant編集POSTが対象を更新して一覧へ戻ること。
    # 目的: 更新usecaseへのHTTPフォーム配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    assistant_id = _seed_base_assistant(app, tmp_path, "Ops")
    client = started_test_client(app)
    _login(client)
    edit_page = client.get(f"/admin/base-assistants/{assistant_id}/edit")

    response = client.post(
        f"/admin/base-assistants/{assistant_id}/edit",
        data={
            "name": "Ops Updated",
            "description": "更新済み",
            "system_prompt": "be precise",
            "user_prompts": "summarize",
            "connection_provider_id": "openai",
            "model": "gpt-5",
            "max_history_messages": "12",
            "generation_config_json": '{"temperature": 0.1}',
            "_csrf_token": _csrf_token(edit_page.text),
        },
        follow_redirects=False,
    )
    listed = client.get("/admin/base-assistants")

    assert response.status_code == 303
    assert "Ops Updated" in listed.text
    captured = capsys.readouterr()
    assert "audit.base_assistant.updated" in captured.err


def test_admin_base_assistant_delete_route_redirects_and_hides_assistant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 管理者のBaseAssistant削除POSTが対象を一覧から隠すこと。
    # 目的: 削除usecaseへのHTTPフォーム配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    assistant_id = _seed_base_assistant(app, tmp_path, "Ops")
    client = started_test_client(app)
    _login(client)
    listed = client.get("/admin/base-assistants")

    response = client.post(
        f"/admin/base-assistants/{assistant_id}/delete",
        data={"_csrf_token": _csrf_token(listed.text)},
        follow_redirects=False,
    )
    after_delete = client.get("/admin/base-assistants")

    assert response.status_code == 303
    assert "Ops" not in after_delete.text
    captured = capsys.readouterr()
    assert "audit.base_assistant.deleted" in captured.err


def test_admin_base_assistant_index_shows_base_specific_columns(
    tmp_path: Path,
) -> None:
    # 観点: 基本アシスタント一覧は接続先や履歴など基本アシスタント固有の情報を表示すること。
    # 目的: 個人アシスタント向けの表示分岐を持ち込まず、専用テンプレート責務を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    _seed_base_assistant(app, tmp_path, "Default", allow_file_upload=True)
    client = started_test_client(app)
    _login(client)

    response = client.get("/admin/base-assistants")

    assert response.status_code == 200
    assert "Provider" in response.text
    assert "History" in response.text
    assert "File upload" in response.text
    assert "Owner" not in response.text
    assert "Visibility" not in response.text


def test_base_assistant_form_shows_single_empty_user_prompt_by_default(
    tmp_path: Path,
) -> None:
    # 観点: 新規BaseAssistantフォームは＋操作なしで空のユーザープロンプト欄を1つ出すこと。
    # 目的: 初回入力時に最初の入力欄が開いた状態で表示される契約を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    _write_provider_config(tmp_path)
    client = started_test_client(app)
    _login(client)

    response = client.get("/admin/base-assistants/new")

    assert response.status_code == 200
    assert response.text.count('name="user_prompts"') == 1


def test_base_assistant_form_does_not_add_blank_user_prompt_when_editing(
    tmp_path: Path,
) -> None:
    # 観点: 既存プロンプトがある編集フォームは保存済み欄だけを表示すること。
    # 目的: 初期表示用の空欄が編集時に余分なプロンプトとして混ざらないようにする。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    assistant_id = _seed_base_assistant(
        app,
        tmp_path,
        "Prompted",
        user_prompts=["一つ目", "二つ目"],
    )
    client = started_test_client(app)
    _login(client)

    response = client.get(f"/admin/base-assistants/{assistant_id}/edit")

    assert response.status_code == 200
    assert response.text.count('name="user_prompts"') == 2
    assert "一つ目" in response.text
    assert "二つ目" in response.text


def test_base_assistant_form_shows_empty_user_prompt_when_editing_without_prompts(
    tmp_path: Path,
) -> None:
    # 観点: 既存BaseAssistantにユーザープロンプトがない場合も空の入力欄を1つ出すこと。
    # 目的: 編集画面でプロンプトを追加できる入口を視覚的に分かる状態にする。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    assistant_id = _seed_base_assistant(app, tmp_path, "Empty Prompt", user_prompts=[])
    client = started_test_client(app)
    _login(client)

    response = client.get(f"/admin/base-assistants/{assistant_id}/edit")

    assert response.status_code == 200
    assert response.text.count('name="user_prompts"') == 1
    assert 'placeholder="例：短く返答します"' in response.text


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
        password_pepper="test-pepper",
    )


def _login(client: TestClient) -> None:
    _ensure_initial_admin(client)
    login_token = _csrf_token(client.get("/login").text)
    response = client.post(
        "/login",
        data={
            "login_name": "admin",
            "password": "adminpass",
            "_csrf_token": login_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _ensure_initial_admin(client: TestClient) -> None:
    """初回セットアップ画面から既定管理者を用意する。"""
    page = client.get("/setup/admin", follow_redirects=False)
    if page.status_code != 200:
        return
    response = client.post(
        "/setup/admin",
        data={
            "login_name": "admin",
            "password": "adminpass",
            "_csrf_token": _csrf_token(page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _seed_base_assistant(
    app: FastAPI,
    tmp_path: Path,
    name: str,
    *,
    allow_file_upload: bool = False,
    user_prompts: list[str] | None = None,
) -> str:
    _write_provider_config(tmp_path)
    database = usecase_runtime_for(app).database
    with database.connect() as conn:
        created = BaseAssistantRepository(conn).save(
            BaseAssistant(
                id=str(uuid4()),
                name=name,
                description="",
                system_prompt="system",
                user_prompts=user_prompts or [],
                connection_provider_id="openai",
                model="gpt-5-mini",
                generation_config={},
                max_history_messages=40,
                allow_file_upload=allow_file_upload,
            )
        )
        conn.commit()
        return created.id


def _write_provider_config(tmp_path: Path) -> None:
    (tmp_path / "connection_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "api_mode": "responses",
                        "api_key": "test",
                        "base_url": "https://api.openai.com/v1",
                        "allowed_models": ["gpt-5", "gpt-5-mini"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
