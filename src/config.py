"""アプリ起動時に使う設定値と固定接続先定義の読み込みを担当する。

このファイルはファイルシステムから設定を読む境界であり、FastAPI、SQLite、
OpenAI SDK には依存しない。接続先定義は ConnectionProvider として
アプリ内部へ渡し、アシスタント本体はDB管理へ委譲する。
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .models import (
    AssistantApiMode,
    AssistantGenerationConfig,
    ConnectionProvider,
    JsonValue,
    is_assistant_config_value,
)

PROJECT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_ROOT.parent
DATA_DIR = REPO_ROOT / "data"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppConfig:
    """アプリ全体の起動設定を表す。"""

    data_dir: Path = DATA_DIR
    log_dir: Path = DATA_DIR / "logs"
    db_path: Path = DATA_DIR / "data.sqlite"
    uploads_dir: Path = DATA_DIR / "uploads"
    templates_dir: Path = PROJECT_ROOT / "templates"
    static_dir: Path = PROJECT_ROOT / "static"
    session_secret: str = ""
    password_pepper: str = ""
    session_cookie_name: str = "new_chat_session"
    session_cookie_secure: bool = False
    log_level: str = "INFO"


def load_app_config(data_dir: Path = DATA_DIR) -> AppConfig:
    """app_config.jsonからアプリ起動設定を読み込み、AppConfigを返す。

    Args:
        data_dir: app_config.json、DB、logs、uploadsを置くデータディレクトリ。

    Returns:
        ファイル設定と既定値を合成したAppConfig。

    app_config.json は必須設定ファイルとして扱い、秘密値またはCookieの
    Secure属性設定が欠落している場合は起動前に明示的に失敗する。
    """
    path = data_dir / "app_config.json"
    raw = _read_app_config_json(path)
    secret = _read_config_str(raw, "session_secret")
    if not secret:
        raise ValueError("app_config.json session_secret is required")
    password_pepper = _read_config_str(raw, "password_pepper")
    if not password_pepper:
        raise ValueError("app_config.json password_pepper is required")
    session_cookie_secure = _read_config_bool(raw, "session_cookie_secure")
    return AppConfig(
        data_dir=data_dir,
        log_dir=data_dir / "logs",
        db_path=data_dir / "data.sqlite",
        uploads_dir=data_dir / "uploads",
        session_secret=secret,
        password_pepper=password_pepper,
        session_cookie_name=_read_config_str(raw, "session_cookie_name")
        or AppConfig.session_cookie_name,
        session_cookie_secure=session_cookie_secure,
        log_level=_read_config_str(raw, "log_level") or AppConfig.log_level,
    )


def _read_app_config_json(path: Path) -> dict[str, JsonValue]:
    """app_config.jsonをdictとして読み込む。

    Args:
        path: 読み込み対象ファイル。

    Returns:
        JSON object。

    Raises:
        FileNotFoundError: ファイルがない場合。
        ValueError: JSONがobjectでない場合。
        json.JSONDecodeError: JSON構文が壊れている場合。
    """
    raw: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("app_config.json must be a JSON object")
    return raw


def _read_config_str(config: dict[str, JsonValue], key: str) -> str:
    """JSON objectから空でない文字列設定を取り出す。

    Args:
        config: app_config.jsonから読んだJSON object。
        key: 読み出す設定名。

    Returns:
        前後空白を除いた文字列。値が文字列でなければ空文字。
    """
    value = config.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _read_config_bool(config: dict[str, JsonValue], key: str) -> bool:
    """JSON objectから必須の真偽値設定を取り出す。

    Args:
        config: app_config.jsonから読んだJSON object。
        key: 読み出す設定名。

    Returns:
        JSONの真偽値。

    Raises:
        ValueError: 設定が欠落しているか、真偽値でない場合。

    文字列や数値を暗黙変換せず、運用設定の誤りを起動時に検知する。
    """
    value = config.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"app_config.json {key} must be a boolean")
    return value


def default_connection_provider() -> ConnectionProvider:
    """接続先定義がない場合に使う安全な既定Providerを返す。"""
    return ConnectionProvider(
        id="default",
        name="Default",
        description="Set data/connection_providers.json to call a real model.",
        api_mode="chat_completions",
        base_url=None,
        api_key="",
        allowed_models=[],
        default_options={},
    )


def load_connection_providers(data_dir: Path) -> list[ConnectionProvider]:
    """connection_providers.json から固定接続先一覧を読み込む。"""
    path = data_dir / "connection_providers.json"
    if not path.exists():
        logger.warning(
            "providers.load missing path=%s result=default reason=file_missing",
            path,
        )
        return [default_connection_provider()]
    try:
        raw: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning(
            "providers.load invalid_json path=%s result=default reason=invalid_json",
            path,
        )
        return [default_connection_provider()]
    if not isinstance(raw, dict):
        logger.warning(
            "providers.load invalid_shape path=%s result=default reason=invalid_shape",
            path,
        )
        return [default_connection_provider()]
    items_value = raw.get("providers")
    if not isinstance(items_value, list):
        logger.warning(
            "providers.load invalid_shape path=%s result=default reason=invalid_shape",
            path,
        )
        return [default_connection_provider()]
    providers: list[ConnectionProvider] = []
    rejected_count = 0
    for item in items_value:
        if not isinstance(item, dict):
            rejected_count += 1
            continue
        provider = _connection_provider_from_dict(item)
        if provider is not None:
            providers.append(provider)
        else:
            rejected_count += 1
    logger.debug(
        "providers.load path=%s accepted_count=%s rejected_count=%s",
        path,
        len(providers),
        rejected_count,
    )
    if not providers:
        logger.warning(
            "providers.load empty path=%s accepted_count=0 result=default reason=no_valid_provider",
            path,
        )
        return [default_connection_provider()]
    return providers


def connection_provider_by_id(
    providers: list[ConnectionProvider],
    provider_id: str,
) -> ConnectionProvider | None:
    """Provider IDから一致する接続先定義を取得する。"""
    for provider in providers:
        if provider.id == provider_id:
            return provider
    return None


def _connection_provider_from_dict(
    item: dict[str, JsonValue],
) -> ConnectionProvider | None:
    """JSONの1項目をConnectionProviderへ変換する。"""
    raw_id = item.get("id")
    raw_name = item.get("name")
    provider_id = raw_id.strip() if isinstance(raw_id, str) else ""
    if not provider_id:
        provider_id = raw_name.strip() if isinstance(raw_name, str) else ""
    if not provider_id:
        return None
    api_mode = _read_api_mode(item.get("api_mode"))
    if api_mode is None:
        return None
    default_options = _read_generation_config(item.get("default_options"))
    allowed_models = _read_allowed_models(item.get("allowed_models"))
    api_key = _read_api_key(item)
    base_url_value = item.get("base_url")
    description_value = item.get("description")
    return ConnectionProvider(
        id=provider_id,
        name=raw_name if isinstance(raw_name, str) and raw_name else provider_id,
        description=description_value if isinstance(description_value, str) else "",
        api_mode=api_mode,
        base_url=base_url_value if isinstance(base_url_value, str) else None,
        api_key=api_key,
        allowed_models=allowed_models,
        default_options=default_options,
    )


def _read_api_mode(value: object) -> AssistantApiMode | None:
    if value == "responses":
        return "responses"
    if value == "chat_completions":
        return "chat_completions"
    return None


def _read_api_key(item: dict[str, JsonValue]) -> str:
    """Provider定義からAPI keyを読み込む。

    Args:
        item: connection_providers.json のProvider定義。

    Returns:
        api_keyが空でない文字列ならその値。それ以外は空文字。
    """
    inline_key = item.get("api_key")
    if isinstance(inline_key, str) and inline_key:
        return inline_key
    return ""


def _read_allowed_models(value: JsonValue) -> list[str]:
    """Provider定義から利用可能モデル名の一覧を読み込む。

    Args:
        value: JSONから読んだallowed_models値。

    Returns:
        空白でない文字列だけを残したモデル名一覧。
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _read_generation_config(value: JsonValue) -> AssistantGenerationConfig:
    """Provider定義の生成オプションをアプリ内部型へ変換する。

    Args:
        value: connection_providers.json の default_options 値。

    Returns:
        LLM APIへ渡せる値だけを残した生成オプション。
    """
    if not isinstance(value, dict):
        return {}
    config: AssistantGenerationConfig = {}
    for raw_key, raw_item in value.items():
        if is_assistant_config_value(raw_item):
            config[raw_key] = raw_item
    return config
