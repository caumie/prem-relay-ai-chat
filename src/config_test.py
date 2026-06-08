
import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from src.config import (
    AppConfig,
    connection_provider_by_id,
    default_connection_provider,
    load_app_config,
    load_connection_providers,
)


def test_load_app_config_requires_app_config_file(tmp_path: Path) -> None:
    # 観点: app_config.jsonがない場合は自動生成せずエラーにすること。
    # 目的: 必須運用設定の欠落を起動時に明示し、意図しない既定値起動を防ぐ。
    with pytest.raises(FileNotFoundError):
        load_app_config(tmp_path)


def test_load_app_config_reads_application_settings_from_json(tmp_path: Path) -> None:
    # 観点: app_config.jsonからアプリ全体の運用設定を読み込めること。
    # 目的: cookie名、初期管理者、ログレベルをコード変更なしで変えられる境界を固定する。
    (tmp_path / "app_config.json").write_text(
        json.dumps(
            {
                "session_secret": "secret",
                "session_cookie_name": "custom_session",
                "admin_login_name": "root",
                "admin_password": "rootpass",
                "log_level": "INFO",
            }
        ),
        encoding="utf-8",
    )

    config = load_app_config(tmp_path)

    assert config == AppConfig(
        data_dir=tmp_path,
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "data.sqlite",
        uploads_dir=tmp_path / "uploads",
        session_secret="secret",
        session_cookie_name="custom_session",
        admin_login_name="root",
        admin_password="rootpass",
        log_level="INFO",
    )


def test_load_app_config_requires_session_secret(tmp_path: Path) -> None:
    # 観点: session_secretがないapp_config.jsonでは起動設定を作らないこと。
    # 目的: セッション署名秘密値を必須設定にし、自動生成や空値での起動を防ぐ。
    (tmp_path / "app_config.json").write_text(
        json.dumps({"log_level": "WARNING", "admin_login_name": "owner"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="session_secret"):
        load_app_config(tmp_path)


def test_app_config_example_json_exists() -> None:
    # 観点: data配下にapp_config.json作成用のサンプルが置かれていること。
    # 目的: 必須設定ファイルを自動生成しない代わりに、利用者が参照できる雛形を固定する。
    sample = Path("data/app_config.example.json")

    assert sample.is_file()
    loaded = json.loads(sample.read_text(encoding="utf-8"))
    assert isinstance(loaded.get("session_secret"), str)
    assert isinstance(loaded.get("session_cookie_name"), str)
    assert isinstance(loaded.get("admin_login_name"), str)
    assert isinstance(loaded.get("admin_password"), str)
    assert isinstance(loaded.get("log_level"), str)


def test_load_connection_providers_returns_default_when_file_is_missing(
    tmp_path: Path,
) -> None:
    # 観点: connection_providers.jsonがない環境でも起動用の既定Providerが得られること。
    # 目的: 設定ファイル欠落をアプリ全体の起動失敗に直結させない。
    providers = load_connection_providers(tmp_path)

    assert providers == [default_connection_provider()]


def test_load_connection_providers_reads_api_key_from_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: Provider定義のapi_key_envから秘密情報を読み込み、DBへ持ち込まないこと。
    # 目的: 接続先秘密情報を固定JSONと環境変数の責務へ分離する。
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")
    (tmp_path / "connection_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "description": "Responses",
                        "api_mode": "responses",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_env": "OPENAI_API_KEY",
                        "allowed_models": ["gpt-5", "gpt-5-mini"],
                        "default_options": {"temperature": 0.2},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    provider = load_connection_providers(tmp_path)[0]

    assert provider.id == "openai"
    assert provider.api_key == "env-secret"
    assert provider.allowed_models == ["gpt-5", "gpt-5-mini"]
    assert provider.default_options == {"temperature": 0.2}


def test_load_connection_providers_keeps_nested_default_options(
    tmp_path: Path,
) -> None:
    # 観点: Provider既定オプションのネストしたreasoning設定を読み込めること。
    # 目的: 固定設定でもResponses APIの階層パラメータを失わない契約を固定する。
    (tmp_path / "connection_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "api_mode": "responses",
                        "default_options": {
                            "reasoning": {"effort": "low", "summary": "auto"},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    provider = load_connection_providers(tmp_path)[0]

    assert provider.default_options == {
        "reasoning": {"effort": "low", "summary": "auto"},
    }


def test_load_connection_providers_reads_inline_api_key_and_defaults(
    tmp_path: Path,
) -> None:
    # 観点: Provider定義がinline api_keyを持つ場合も読み込めること。
    # 目的: ローカル接続先など環境変数を使わない設定の入口を保持する。
    (tmp_path / "connection_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "local",
                        "name": "Local",
                        "api_mode": "chat_completions",
                        "base_url": "http://localhost:11434/v1",
                        "api_key": "dummy",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    provider = load_connection_providers(tmp_path)[0]

    assert provider.description == ""
    assert provider.api_key == "dummy"
    assert provider.allowed_models == []
    assert provider.default_options == {}


def test_load_connection_providers_falls_back_when_shape_is_invalid(
    tmp_path: Path,
) -> None:
    # 観点: providersの形が壊れている場合は既定Providerへ倒すこと。
    # 目的: 運用者編集JSONの破損を安全に閉じ込める。
    (tmp_path / "connection_providers.json").write_text(
        json.dumps({"providers": {"id": "broken"}}),
        encoding="utf-8",
    )

    assert load_connection_providers(tmp_path) == [default_connection_provider()]


def test_connection_provider_by_id_returns_requested_provider_or_none(
    tmp_path: Path,
) -> None:
    # 観点: provider idから該当Providerを取得でき、欠落時はNoneになること。
    # 目的: アシスタント実行時の接続先解決を設定層の共通ルールにする。
    (tmp_path / "connection_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {"id": "first", "name": "First", "api_mode": "responses"},
                    {"id": "second", "name": "Second", "api_mode": "responses"},
                ]
            }
        ),
        encoding="utf-8",
    )
    providers = load_connection_providers(tmp_path)

    assert connection_provider_by_id(providers, "second") == providers[1]
    assert connection_provider_by_id(providers, "missing") is None
