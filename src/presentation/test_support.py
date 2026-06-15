"""presentation route テスト用の補助境界を定義する。"""

from dataclasses import dataclass
from weakref import WeakKeyDictionary

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.usecase.initial_setup import initialize_database_schema
from src.usecase.runtime import UsecaseRuntime, get_usecase_runtime


@dataclass(frozen=True)
class TestApplication:
    """presentation route テストで使う起動済みアプリ一式を表す。

    Args:
        client: lifespan 開始済みの TestClient。
        usecase_runtime: このアプリに紐づく usecase runtime。
    """

    client: TestClient
    usecase_runtime: UsecaseRuntime
    __test__ = False


_runtime_by_app: WeakKeyDictionary[FastAPI, UsecaseRuntime] = WeakKeyDictionary()


def started_test_client(
    app: FastAPI,
    *,
    follow_redirects: bool = True,
) -> TestClient:
    """lifespanを開始済みの TestClient を返す。

    Args:
        app: テスト対象の FastAPI アプリ。
        follow_redirects: TestClient の既定リダイレクト追従設定。

    Returns:
        lifespan startup 済みの TestClient。

    routeテストが起動時初期化を正しく通した状態でHTTP境界を検証できるようにする。
    """
    _remember_current_usecase_runtime(app)
    client = TestClient(app, follow_redirects=follow_redirects)
    client.__enter__()
    return client


def started_test_application(
    app: FastAPI,
    *,
    follow_redirects: bool = True,
) -> TestApplication:
    """lifespan を開始済みの TestApplication を返す。

    Args:
        app: テスト対象の FastAPI アプリ。
        follow_redirects: TestClient の既定リダイレクト追従設定。

    Returns:
        lifespan startup 済みの TestApplication。

    route テストが対象 app に紐づく runtime と HTTP client を同時に持てるようにする。
    """
    client = started_test_client(app, follow_redirects=follow_redirects)
    runtime = usecase_runtime_for(app)
    return TestApplication(client=client, usecase_runtime=runtime)


def usecase_runtime_for(app: FastAPI) -> UsecaseRuntime:
    """テスト対象 app に紐づく usecase runtime を返す。

    Args:
        app: build_app が生成した FastAPI アプリ。

    Returns:
        この app に紐づく UsecaseRuntime。
    """
    runtime = _runtime_by_app.get(app)
    if runtime is None:
        _remember_current_usecase_runtime(app)
        runtime = _runtime_by_app.get(app)
    if runtime is None:
        raise RuntimeError("test app runtime is not bound")
    initialize_database_schema()
    return runtime


def _remember_current_usecase_runtime(app: FastAPI) -> None:
    """現在の usecase runtime を対象 app に対応付けて保持する。

    Args:
        app: build_app が生成した FastAPI アプリ。

    Returns:
        None。

    build_app 直後の runtime を test helper 側で記録し、production code に
    テスト専用の attribute を持ち込まずに済むようにする。
    """
    _runtime_by_app[app] = get_usecase_runtime()
