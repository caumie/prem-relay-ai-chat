"""トップページ route の遷移分岐を検証する。"""

import json
from base64 import b64encode
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from starlette.middleware.sessions import SessionMiddleware

from src.config import AppConfig
from src.infrastructure import Database
from src.models import LlmMessage
from src.presentation import index as index_routes
from src.presentation.test_support import started_test_client
from src.service.response_service import StreamEvent
from src.usecase.initial_setup import create_initial_admin
from src.usecase.runtime import init_usecase_runtime


class FakeResponder:
    """index routeテスト用の空 responder。"""

    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        """引数を受け取り、応答イベントを生成しない。

        Args:
            messages: LLM へ渡すメッセージ一覧。
            assistant: 応答生成に使う assistant。

        Returns:
            空の非同期イテレータ。

        index route テストでは LLM 応答を使わないため、起動依存だけ満たす。
        """
        _ = (messages, assistant)
        events: list[StreamEvent] = []
        for event in events:
            yield event


def test_index_redirects_to_setup_admin_when_initial_setup_is_not_completed(
    tmp_path: Path,
) -> None:
    # 観点: 初期セットアップ未完了時は未ログインでも /setup/admin へ遷移すること。
    # 目的: アプリ入口で初期管理者作成導線が最優先される仕様を固定する。
    client = _client(tmp_path)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/setup/admin"


def test_index_redirects_to_login_when_initial_setup_is_completed_and_user_is_not_logged_in(
    tmp_path: Path,
) -> None:
    # 観点: 初期セットアップ完了かつ未ログイン時は /login へ遷移すること。
    # 目的: 通常の未認証ユーザーが認証画面へ案内される仕様を固定する。
    client = _client(tmp_path)
    _create_initial_admin()

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_index_redirects_to_chat_when_initial_setup_is_completed_and_user_is_logged_in(
    tmp_path: Path,
) -> None:
    # 観点: 初期セットアップ完了かつログイン済み時は /chat へ遷移すること。
    # 目的: 認証済みユーザーがチャット画面へ入れる通常導線を固定する。
    client = _client(tmp_path)
    admin = _create_initial_admin()
    _set_logged_in_session(client, user_id=admin.id)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/chat"


def test_index_prioritizes_initial_setup_over_logged_in_session(
    tmp_path: Path,
) -> None:
    # 観点: 初期セットアップ未完了時は、ログインセッションがあっても /setup/admin が優先されること。
    # 目的: 判定順序がログイン状態より初期セットアップ状態を優先する設計であることを明確にする。
    client = _client(tmp_path)
    _set_logged_in_session(client, user_id=999)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/setup/admin"


def _client(tmp_path: Path):
    """テスト対象の index router だけを登録した HTTP client を返す。

    Args:
        tmp_path: テスト専用ファイル配置先。

    Returns:
        起動済み TestClient。

    index route 単体の責務を検証し、route 登録全体のテストと切り分けるため。
    """
    config = AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
        password_pepper="test-pepper",
    )
    init_usecase_runtime(config=config, responder=FakeResponder())
    Database(config.db_path).initialize()

    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        session_cookie=config.session_cookie_name,
        same_site="lax",
        https_only=config.session_cookie_secure,
    )
    app.include_router(index_routes.router)
    return started_test_client(app, follow_redirects=False)


def _create_initial_admin():
    """初回管理者を作成して返す。

    Args:
        なし。

    Returns:
        作成された管理者ユーザー。

    初期セットアップ完了状態を route テストから自然に表現するため。
    """
    return create_initial_admin(login_name="owner", password="ownerpass")


def _set_logged_in_session(client: TestClient, *, user_id: int) -> None:
    """ログイン済みセッション Cookie を client へ設定する。

    Args:
        client: Cookie を設定する TestClient。
        user_id: セッションへ保存するユーザーID。

    Returns:
        None。

    auth route を経由せず、index route 単体テストでログイン状態だけを表現するため。
    """
    cookie = _signed_session_cookie({"user_id": user_id})
    client.cookies.set(AppConfig.session_cookie_name, cookie)


def _signed_session_cookie(session: dict[str, int]) -> str:
    """SessionMiddleware 互換の署名付き Cookie 値を返す。

    Args:
        session: Cookie に保存する session payload。

    Returns:
        SessionMiddleware が読める署名済み文字列。

    route テストから request.session を直接触らず、HTTP 境界のまま状態を作るため。
    """
    encoded = b64encode(json.dumps(session).encode("utf-8"))
    return TimestampSigner("test-secret").sign(encoded).decode("utf-8")
