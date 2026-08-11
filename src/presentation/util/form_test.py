"""共有フォーム値変換の挙動を検証する。"""

import pytest

from src.models import UserInputError
from src.presentation.util.form import (
    form_string_list,
    optional_form_string,
    required_form_string,
)


def test_form_string_helpers_normalize_values() -> None:
    """必須・任意・複数値のフォーム文字列を同じ規則で整形する。"""
    # 観点: フォーム文字列の前後空白と空欄を共通規則で処理すること。
    # 目的: 各routeが同じ入力整形処理を重複して持たないようにする。
    assert required_form_string("  name  ", "name") == "name"
    assert optional_form_string("  description  ") == "description"
    assert form_string_list([" one ", "", "  ", "two"]) == ["one", "two"]


def test_required_form_string_rejects_non_string_or_blank_values() -> None:
    """必須フォーム値が文字列でない場合や空欄の場合に拒否する。"""
    # 観点: 必須値の欠落を共通の入力エラーへ変換すること。
    # 目的: routeごとに異なる必須値判定を持たせず、HTTPエラー変換を揃える。
    for value in (None, "  ", 1):
        with pytest.raises(UserInputError, match="name is required"):
            required_form_string(value, "name")

