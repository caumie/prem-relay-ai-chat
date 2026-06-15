"""usecase runtime の初期化契約を検証する。"""

from pathlib import Path

from src.config import AppConfig
from src.usecase.runtime import init_usecase_runtime


def test_init_usecase_runtime_keeps_configured_database_and_config(
    tmp_path: Path,
) -> None:
    """設定から共有runtimeを初期化する。"""
    # 観点: usecase runtime が設定されたDBパスと設定そのものを保持すること。
    # 目的: config由来の値をruntime内で個別依存へ分解しない境界を固定する。
    config = AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="session-secret",
        password_pepper="password-pepper",
    )

    runtime = init_usecase_runtime(config=config)

    assert runtime.database.db_path == tmp_path / "chat.sqlite"
    assert runtime.config == config
    assert not hasattr(runtime, "password_pepper")
