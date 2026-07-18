"""models の入力正規化と既定値の契約を検証する。"""

import pytest

from src.models import (
    MessageRole,
    UserInputError,
    default_assistant_file_extensions,
    normalize_chat_input,
    normalize_message_content,
)


def test_normalize_message_content_strips_surrounding_space() -> None:
    # 観点: フォーム由来の本文が保存前に正規化されること。
    # 目的: presentation層ごとにstrip処理が散らばらない共通ルールを固定する。
    assert normalize_message_content("  hello\n") == "hello"


def test_normalize_message_content_rejects_blank_text() -> None:
    # 観点: 空白だけの入力はチャット本文として扱わないこと。
    # 目的: 無効なMessageをservice/repositoryへ渡さない境界を固定する。
    with pytest.raises(UserInputError):
        normalize_message_content(" \n\t ")


def test_normalize_chat_input_allows_attachment_only_message() -> None:
    # 観点: 添付ファイルがあれば本文なしでも投稿として成立すること。
    # 目的: 画像だけ、PDFだけの投稿をservice層で正しく扱う入力境界を固定する。
    assert normalize_chat_input(" \n", attachment_count=1) == ""


def test_normalize_chat_input_rejects_empty_message_without_attachment() -> None:
    # 観点: 本文も添付もない投稿は拒否すること。
    # 目的: 空のMessageをDBやLLM入力へ流さない。
    with pytest.raises(UserInputError):
        normalize_chat_input(" \n", attachment_count=0)


def test_message_role_exposes_llm_role_name() -> None:
    # 観点: アプリ内部のroleからLLM API用のrole名へ変換できること。
    # 目的: 外部APIの文字列仕様を呼び出し側へ散らさない設計を固定する。
    assert MessageRole.USER.to_llm_role() == "user"
    assert MessageRole.ASSISTANT.to_llm_role() == "assistant"


def test_default_assistant_file_extensions_follows_allowed_type_definitions() -> None:
    # 観点: アシスタントの既定値は種別ごとの許可拡張子定義に従うこと。
    # 目的: 保存層とフォームの既定値が別々に更新される不整合を防ぐ。
    assert default_assistant_file_extensions() == [
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "txt",
        "md",
        "pdf",
    ]
