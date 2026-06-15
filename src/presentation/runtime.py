"""presentation 実行依存の初期化を担当する。"""

from dataclasses import dataclass

from fastapi.templating import Jinja2Templates


@dataclass(frozen=True)
class PresentationRuntime:
    """presentation 全体で共有する長寿命依存を保持する。

    Args:
        templates: HTML 描画に使う Jinja2Templates。
    """

    templates: Jinja2Templates


runtime: PresentationRuntime | None = None


def init_presentation_runtime(
    *, templates: Jinja2Templates
) -> PresentationRuntime:
    """presentation runtime を初期化して返す。

    Args:
        templates: presentation runtime の生成に使うテンプレート設定。

    Returns:
        初期化した PresentationRuntime。
    """
    global runtime
    runtime = PresentationRuntime(
        templates=templates,
    )
    return runtime

def get_presentation_runtime() -> PresentationRuntime:
    """初期化済みの共有 presentation runtime を返す。

    Returns:
        初期化済みの PresentationRuntime。
    """
    if runtime is None:
        raise RuntimeError("Presentation runtime is not initialized")
    return runtime
