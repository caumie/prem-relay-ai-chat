"""FastAPIアプリ生成時のroute配線とlifespan起動初期化を検証する。"""

from collections.abc import AsyncIterator, Sequence
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from starlette.routing import Mount, Route

from src.app import build_app
from src.config import AppConfig
from src.models import LlmMessage
from src.presentation.test_support import started_test_client
from src.service.response_service import StreamEvent
from src.usecase.runtime import get_usecase_runtime


def test_importing_app_module_does_not_require_runtime_config(tmp_path: Path) -> None:
    """設定ファイルなしでアプリ生成関数をimportできることを検証する。"""
    # 観点: src.appのimportだけではapp_config.jsonを読み込まないこと。
    # 目的: テスト収集や静的解析をローカル専用の実行時設定から分離する。
    repo_root = Path(__file__).resolve().parent.parent
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repo_root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path\n"
                "from unittest.mock import patch\n"
                "original_read_text = Path.read_text\n"
                "def guarded_read_text(path, *args, **kwargs):\n"
                "    if path.name == 'app_config.json':\n"
                "        raise AssertionError('import must not read app_config.json')\n"
                "    return original_read_text(path, *args, **kwargs)\n"
                "with patch('pathlib.Path.read_text', guarded_read_text):\n"
                "    from src.app import build_app\n"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        events: list[StreamEvent] = []
        for event in events:
            yield event


def _route_paths(routes: Sequence[object]) -> set[str]:
    return {route.path for route in routes if isinstance(route, Route | Mount)}


def test_build_app_registers_routes_without_exposing_runtime_state(
    tmp_path: Path,
) -> None:
    # 観点: build_appがrouteだけを登録し、依存をapp.stateへ公開しないこと。
    # 目的: presentation層からDBやserviceへ抜ける入口をappに残さない境界を固定する。
    responder = FakeResponder()
    config = _config(tmp_path)

    app = build_app(config, responder=responder)

    assert not hasattr(app.state, "config")
    assert not hasattr(app.state, "database")
    assert not hasattr(app.state, "responder")
    assert not hasattr(app.state, "response_service")
    assert not hasattr(app.state, "attachment_storage")
    assert _route_paths(app.routes) >= {
        "/chat",
        "/login",
        "/static",
    }
    assert "/assets" not in _route_paths(app.routes)


def test_lifespan_initializes_database_without_creating_initial_admin(
    tmp_path: Path,
) -> None:
    # 観点: lifespan起動時にDB初期化だけが行われ管理者は自動作成されないこと。
    # 目的: 起動処理とユーザー主導の初回管理者作成を分離する境界を固定する。
    app = build_app(_config(tmp_path))

    with TestClient(app):
        database = get_usecase_runtime().database

    with database.connect() as conn:
        count = conn.execute("select count(*) from active_users").fetchone()[0]

    assert count == 0


def test_build_app_does_not_initialize_database_before_lifespan(
    tmp_path: Path,
) -> None:
    # 観点: build_app単体ではDBファイルを作らず起動処理をlifespanへ遅延すること。
    # 目的: 初期化責務をFastAPI起動タイミングへ閉じ込める。
    config = _config(tmp_path)

    build_app(config)

    assert not config.db_path.exists()


def test_build_app_passes_responder_to_usecase_runtime_only(
    tmp_path: Path,
) -> None:
    """responder 差し替えを usecase runtime の責務へ閉じ込める。"""
    # 観点: build_app に渡した responder が usecase runtime の response_service にだけ保持されること。
    # 目的: responder 注入の責務を app から presentation 配線へ拡散させない境界を固定する。
    responder = FakeResponder()

    build_app(_config(tmp_path), responder=responder)

    usecase_runtime = get_usecase_runtime()
    assert usecase_runtime.response_service.responder is responder


def test_session_cookie_secure_setting_controls_secure_attribute(
    tmp_path: Path,
) -> None:
    # 観点: session_cookie_secure設定に応じてSession CookieのSecure属性が切り替わること。
    # 目的: HTTP開発環境とHTTPS本番環境を同じアプリ実装で運用できるようにする。
    secure_config = _config(tmp_path / "secure", session_cookie_secure=True)
    insecure_config = _config(tmp_path / "insecure", session_cookie_secure=False)

    with TestClient(build_app(secure_config), base_url="https://testserver") as client:
        secure_cookie = client.get("/login").headers["set-cookie"]
    with TestClient(build_app(insecure_config)) as client:
        insecure_cookie = client.get("/login").headers["set-cookie"]

    assert "secure" in secure_cookie.lower()
    assert "secure" not in insecure_cookie.lower()


def test_http_request_id_is_exposed_to_response(tmp_path: Path) -> None:
    # 観点: HTTP requestごとに request_id が生成されること。
    # 目的: クライアントが障害報告時に要求を識別できるようにする。
    client = started_test_client(
        build_app(_config(tmp_path), responder=FakeResponder())
    )

    response = client.get("/login")

    request_id = response.headers["X-Request-ID"]

    assert request_id


def _config(tmp_path: Path, *, session_cookie_secure: bool = False) -> AppConfig:
    """テスト用アプリ設定を返す。

    Args:
        tmp_path: DBとアップロードを置く一時ディレクトリ。
        session_cookie_secure: Session CookieへSecure属性を付けるか。

    Returns:
        アプリ生成に必要な固定値を持つAppConfig。
    """
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
        password_pepper="test-pepper",
        session_cookie_secure=session_cookie_secure,
    )
