"""HTTPフォーム値の共通変換を担当する。

このモジュールはrouteごとのフォーム項目を知らず、文字列の型検証・空白除去・
複数値の空欄除去だけを共通化する。
"""

from collections.abc import Sequence

from ...models import UserInputError


def required_form_string(value: object, field_name: str) -> str:
    """必須フォーム値を空白除去済み文字列として返す。

    Args:
        value: フォームから取り出した値。
        field_name: エラーに表示する項目名。

    Returns:
        前後空白を除いた非空文字列。

    Raises:
        UserInputError: 値が文字列でない、または空欄の場合。

    routeごとに必須文字列の判定とエラーメッセージを複製しないため。
    """
    if not isinstance(value, str) or not value.strip():
        raise UserInputError(f"{field_name} is required")
    return value.strip()


def optional_form_string(value: object) -> str:
    """任意フォーム値を空白除去済み文字列として返す。

    Args:
        value: フォームから取り出した値。

    Returns:
        文字列なら前後空白を除いた値、それ以外なら空文字。

    routeごとの任意文字列変換を同じ入力規則へ揃えるため。
    """
    return value.strip() if isinstance(value, str) else ""


def form_string_list(values: Sequence[object]) -> list[str]:
    """複数フォーム値から空欄を除いた文字列一覧を返す。

    Args:
        values: フォームから取り出した複数値。

    Returns:
        前後空白を除き、空欄を除外した文字列一覧。

    複数入力欄を持つrouteで同じ整形処理を繰り返さないため。
    """
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]

