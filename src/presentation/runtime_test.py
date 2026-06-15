"""presentation runtime の初期化契約を検証する。"""

from pathlib import Path

import pytest
from fastapi.templating import Jinja2Templates

from src.presentation import runtime as presentation_runtime


def test_get_presentation_runtime_raises_when_not_initialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未初期化の presentation runtime を明示的に拒否する。"""
    # 観点: presentation runtime が未初期化状態を RuntimeError として扱うこと。
    # 目的: route 登録前の依存不足を暗黙 None ではなく明示エラーで検出できるようにする。
    monkeypatch.setattr(presentation_runtime, "runtime", None)

    with pytest.raises(RuntimeError, match="Presentation runtime is not initialized"):
        presentation_runtime.get_presentation_runtime()


def test_init_presentation_runtime_keeps_configured_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """設定した templates を共有 runtime へ保持する。"""
    # 観点: presentation runtime が templates を長寿命依存として保持すること。
    # 目的: router ごとの module global ではなく runtime から templates を取得する移行先を固定する。
    monkeypatch.setattr(presentation_runtime, "runtime", None)
    templates = Jinja2Templates(directory=str(tmp_path))

    runtime = presentation_runtime.init_presentation_runtime(templates=templates)

    assert runtime.templates is templates
    assert presentation_runtime.get_presentation_runtime() is runtime
