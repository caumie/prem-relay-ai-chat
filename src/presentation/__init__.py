"""Web route packageの公開入口を定義する。

このファイルは package 外から見える route 配線の入口を扱う。個別 route module の
APIRouter 取り込みと登録順だけをここへ集約し、dependency/context の実体は
各 router または共通 presentation 関数へ委譲する。
"""

from fastapi import FastAPI

from . import index as index_routes
from . import assistant as assistant_routes
from . import auth as auth_routes
from . import chat as chat_routes
from . import setup as setup_routes
from .admin import base_assistant as admin_base_assistant_routes
from .admin import user as admin_user_routes
from .admin import user_assistant as admin_user_assistant_routes
from .runtime import get_presentation_runtime


def register_web_routes(app: FastAPI) -> None:
    """Web route package 全体を FastAPI アプリへ登録する。

    Args:
        app: route を登録する FastAPI インスタンス。

    Returns:
        None。

    presentation runtime が初期化済みであることを確認した上で、
    package 入口で router include を行う。
    """
    get_presentation_runtime()

    app.include_router(index_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(setup_routes.router)
    app.include_router(assistant_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(admin_user_routes.router)
    app.include_router(admin_base_assistant_routes.router)
    app.include_router(admin_user_assistant_routes.router)
