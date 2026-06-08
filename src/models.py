
"""アプリ全体で共有するチャット領域の型と小さなルールを定義する。

このファイルは FastAPI、SQLite、OpenAI SDK などの外部事情を持たない。
presentation / service / repository が同じ語彙を使えるように、
ロール、状態、アシスタント、本文正規化、LLM入力化の境界をここで固定する。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from collections.abc import Awaitable, Callable
from typing import Literal, TypeAlias, TypeGuard


def _empty_message_kinds() -> list["MessageKind"]:
    """Message.kindsのdefault_factory用に型付きの空リストを返す。

    Returns:
        新しい空のMessageKindリスト。

    dataclasses.field(default_factory=list) では静的解析上の要素型が失われるため、
    型の境界を曖昧にしない目的で専用関数にする。
    """
    return []


class UserInputError(ValueError):
    """ユーザー入力がアプリの扱える値に正規化できない場合の例外。

    入力エラーを ValueError の一種として表すことで、presentation 層は
    HTTP 400 やフォームエラーへ変換でき、service 層は無効値を処理しない。
    """


class MessageRole(StrEnum):
    """チャットメッセージの発言者を表す。

    DBやフォーム由来の任意文字列をそのまま扱わず、この列挙型に閉じることで
    表示分岐が受け取る値を限定する。
    """

    USER = "user"
    ASSISTANT = "assistant"

    def to_llm_role(self) -> Literal["user", "assistant"]:
        """LLM APIへ渡せる role 名を返す。

        Returns:
            OpenAI互換APIの messages/input で使う role 文字列。

        現在のアプリでは domain の role 名と LLM role 名は一致するが、
        外部APIの名前を呼び出し側に直接散らさないためにメソッド化する。
        """
        if self is MessageRole.USER:
            return "user"
        return "assistant"


class MessageStatus(StrEnum):
    """assistant 応答生成を含むメッセージの永続状態を表す。

    ユーザー操作のリカバーは明示的に行う方針のため、再起動後の未完了状態は
    自動再実行ではなく failed へ収束させる前提で使う。
    """

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class User:
    """ログイン済み利用者を表す。

    Attributes:
        id: DB上のユーザーID。
        login_name: ログインに使う一意な名前。
        is_admin: 管理画面へアクセスできる管理者ならTrue。
        suspended_at: 休止日時。未休止ならNone。
    """

    id: int
    login_name: str
    is_admin: bool = False
    suspended_at: datetime | None = None


@dataclass(frozen=True)
class Thread:
    """一連のチャット会話をまとめる単位を表す。

    Attributes:
        id: URLとDBで使うスレッドID。
        user_id: 所有者のユーザーID。
        title: サイドバーなどに表示する短いタイトル。
        created_at: 作成日時。
        updated_at: 並び替えに使う最終更新日時。
        deleted_at: 論理削除日時。未削除ならNone。
    """

    id: str
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class Attachment:
    """チャットメッセージへ添付された保存済みファイルを表す。

    Attributes:
        id: URL、message_kinds.content、DBで使う添付ID。
        user_id: 所有者のユーザーID。
        original_filename: 利用者がアップロードしたファイル名。
        stored_path: uploads_dirからの相対保存パス。
        content_type: アップロード時に得たMIME type。
        size_bytes: 保存したファイルサイズ。
        sha256: 保存内容のSHA-256 digest。
        created_at: 保存日時。
    """

    id: str
    user_id: int
    original_filename: str
    stored_path: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


@dataclass(frozen=True)
class PendingUpload:
    """presentation層で受け取った未保存アップロードを表す。

    Attributes:
        filename: 利用者が送信したファイル名。
        content_type: フォーム入力から得たMIME type。空なら保存側で既定値にする。
        read: 指定byte数まで非同期に読み込む関数。
        close: 読み込み完了後にリソースを閉じる関数。
    """

    filename: str
    content_type: str
    read: Callable[[int], Awaitable[bytes]]
    close: Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class MessageKind:
    """メッセージ本文以外の表示・添付要素を表す。

    Attributes:
        kind: text/reasoning/file の種類。
        content: 表示本文またはファイル参照などの内容。
        id: DB保存後に付与されるID。未保存なら None。
        order_index: 同一メッセージ内の表示順。
        metadata_json: 将来拡張用のJSON文字列。
    """

    kind: Literal["text", "reasoning", "file"]
    content: str
    id: int | None = None
    order_index: int = 0
    metadata_json: str | None = None


@dataclass(frozen=True)
class Message:
    """チャットに保存される1つの発言を表す。

    Attributes:
        id: DB上のメッセージID。
        thread_id: 所属するスレッドID。
        role: ユーザー発言かassistant発言か。
        content: 表示・LLM履歴化に使う本文。
        status: 応答生成の状態。ユーザー発言は通常 completed。
        assistant_id: 生成に使ったアシスタントID。未選択時は None。
        kinds: 本文以外の表示要素。未指定なら本文のみとして扱う。
        created_at: 作成日時。
        updated_at: 最終更新日時。
    """

    id: int
    thread_id: str
    role: MessageRole
    content: str
    status: MessageStatus
    assistant_id: str | None
    created_at: datetime
    updated_at: datetime
    kinds: list[MessageKind] = field(default_factory=_empty_message_kinds)


@dataclass(frozen=True)
class ThreadDetail:
    """スレッドとそのメッセージ一覧をまとめて返す読み取りモデル。

    Attributes:
        thread: 対象スレッド。
        messages: 作成順に並んだスレッド内メッセージ。
    """

    thread: Thread
    messages: list[Message]


AssistantApiMode: TypeAlias = Literal["responses", "chat_completions"]
AssistantVisibility: TypeAlias = Literal["private", "public"]
AssistantOptionCategory: TypeAlias = Literal["owned", "system_public", "other_public"]
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
AssistantConfigScalar: TypeAlias = str | int | float | bool
AssistantConfigValue: TypeAlias = (
    AssistantConfigScalar
    | list["AssistantConfigValue"]
    | dict[str, "AssistantConfigValue"]
)
AssistantGenerationConfig: TypeAlias = dict[str, AssistantConfigValue]
LlmContentPart: TypeAlias = dict[str, object]
LlmMessage: TypeAlias = dict[str, str | list[LlmContentPart]]
DEFAULT_ASSISTANT_FILE_EXTENSIONS = ["jpg", "jpeg", "png"]


def default_assistant_file_extensions() -> list[str]:
    """BaseAssistant の既定ファイル許可拡張子を新しいリストで返す。

    Returns:
        dotなし小文字の既定拡張子一覧。

    dataclass の可変既定値を共有しないため、default_factory として使う。
    """
    return list(DEFAULT_ASSISTANT_FILE_EXTENSIONS)


def normalize_file_extensions(extensions: list[str]) -> list[str]:
    """拡張子表記をdotなし小文字へ正規化し、順序を保って重複除去する。

    Args:
        extensions: フォームやDBから得た拡張子一覧。

    Returns:
        空欄を除いたdotなし小文字の拡張子一覧。

    assistantごとの許可設定を保存・判定の両方で同じ形に揃えるため。
    """
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_extension in extensions:
        extension = raw_extension.strip().lower().lstrip(".")
        if extension and extension not in seen:
            seen.add(extension)
            normalized.append(extension)
    return normalized


def is_assistant_config_value(value: JsonValue) -> TypeGuard[AssistantConfigValue]:
    """生成オプションとして保存・送信できるJSON値かを判定する。

    Args:
        value: フォーム、設定ファイル、DB JSONから得たJSON値。

    Returns:
        文字列、数値、真偽値、またはそれらを再帰的に含む配列・オブジェクトならTrue。

    OpenAI互換APIの生成設定は `reasoning` のような階層パラメータを持つため、
    スカラーだけに潰さずJSON構造を保つ。一方で null は意図しない削除値になりやすいため
    既存方針どおり設定値としては扱わない。
    """
    if isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(is_assistant_config_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            is_assistant_config_value(raw_value) for raw_value in value.values()
        )
    return False


@dataclass(frozen=True)
class ConnectionProvider:
    """固定定義されたLLM接続先を表す。

    Attributes:
        id: Assistantが参照する一意な接続先ID。
        name: 管理画面や編集画面に表示する名前。
        description: 接続先の説明文。
        api_mode: OpenAI互換APIの利用モード。
        base_url: OpenAI互換サーバーのURL。既定APIの場合は None。
        api_key: この接続先で使うAPI key。環境変数経由解決後の値。
        allowed_models: この接続先で利用できるモデル名一覧。空なら制限なし。
        default_options: temperatureなど接続先の既定生成オプション。
    """

    id: str
    name: str
    description: str
    api_mode: AssistantApiMode
    base_url: str | None
    api_key: str
    allowed_models: list[str]
    default_options: AssistantGenerationConfig


@dataclass(frozen=True)
class BaseAssistant:
    """管理者が作成する元アシスタントを表す。

    Attributes:
        id: フォーム値やメッセージ履歴に保存するBaseAssistant ID。
        name: 画面に表示する名前。
        description: 管理・選択時に表示できる説明文。
        system_prompt: 履歴の先頭に追加するシステム指示。
        user_prompts: 各ユーザー発言に前置する指示群。
        connection_provider_id: 接続先として使うConnectionProvider ID。
        model: LLM実行時に指定するモデル名。
        generation_config: 生成オプション。API keyやURLは含めない。
        max_history_messages: LLMへ渡す履歴メッセージ数。
        allow_file_upload: 添付ファイル送信を許可するならTrue。
        allowed_file_extensions: 添付許可時に受け付けるdotなし拡張子一覧。
        deleted_at: 論理削除日時。未削除ならNone。
    """

    id: str
    name: str
    description: str
    system_prompt: str
    user_prompts: list[str]
    connection_provider_id: str
    model: str
    generation_config: AssistantGenerationConfig
    max_history_messages: int
    allow_file_upload: bool
    allowed_file_extensions: list[str] = field(
        default_factory=default_assistant_file_extensions
    )
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class UserAssistant:
    """ユーザーがBaseAssistantへ追記するアシスタントを表す。

    Attributes:
        id: フォーム値やメッセージ履歴に保存するUserAssistant ID。
        base_assistant_id: 元になるBaseAssistant ID。未割り当てならNone。
        owner_user_id: 作成者のユーザーID。
        name: 画面に表示する名前。
        description: 管理・選択時に表示できる説明文。
        user_prompts: BaseAssistantのuser_promptsへ追記する指示群。
        visibility: 作成者以外にも利用できるpublicか、自分だけのprivateか。
        deleted_at: 論理削除日時。未削除ならNone。
    """

    id: str
    base_assistant_id: str | None
    owner_user_id: int
    name: str
    description: str
    user_prompts: list[str]
    visibility: AssistantVisibility
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class AssistantOption:
    """チャット選択肢として表示できるアシスタントを表す。

    Attributes:
        id: チャットPOSTで送るアシスタントID。
        name: 選択肢に表示する名前。
        description: 補助説明。
        allow_file_upload: この選択肢で添付ファイル送信を許可するか。
        allowed_file_extensions: 添付許可時に受け付けるdotなし拡張子一覧。
        kind: base/user のどちらのアシスタントか。
        category: チャットselectで使う表示カテゴリ。
    """

    id: str
    name: str
    description: str
    allow_file_upload: bool
    kind: Literal["base", "user"]
    category: AssistantOptionCategory
    allowed_file_extensions: list[str] = field(
        default_factory=default_assistant_file_extensions
    )
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class ResolvedAssistant:
    """接続先を解決済みの実行用アシスタントを表す。

    Attributes:
        id: 実行元のアシスタントID。
        name: 表示名。
        description: 説明文。
        system_prompt: 履歴先頭へ追加する指示。
        user_prompts: ユーザー発言へ前置する指示群。
        api_mode: OpenAI互換APIの利用モード。
        base_url: OpenAI互換サーバーのURL。既定APIの場合はNone。
        config: API key、モデル名、生成オプション、添付方針を含む実行設定。
        max_history_messages: LLMへ渡す履歴メッセージ数。
    """

    id: str
    name: str
    description: str
    system_prompt: str
    user_prompts: list[str]
    api_mode: AssistantApiMode
    base_url: str | None
    config: AssistantGenerationConfig
    max_history_messages: int


def normalize_message_content(content: str) -> str:
    """ユーザー入力を保存・LLM送信用の本文に正規化する。

    Args:
        content: フォームやAPIから受け取った未検証の本文。

    Returns:
        前後空白を取り除いた、空文字ではない本文。

    Raises:
        UserInputError: チャット本文として扱える文字が残らない場合。

    入力の空白除去と空文字拒否を service より内側に置くことで、
    Web以外の入口でも同じ本文ルールを再利用できるようにする。
    """
    text = content.strip()
    if not text:
        raise UserInputError("content is required")
    return text


def normalize_chat_input(content: str, attachment_count: int) -> str:
    """本文と添付数から、投稿として成立する入力かを検証する。

    Args:
        content: フォームやAPIから受け取った未検証の本文。
        attachment_count: 同じ投稿に含まれる添付ファイル数。

    Returns:
        前後空白を取り除いた本文。添付のみなら空文字。

    Raises:
        UserInputError: 本文も添付もない場合。
    """
    text = content.strip()
    if not text and attachment_count == 0:
        raise UserInputError("content or attachment is required")
    return text
