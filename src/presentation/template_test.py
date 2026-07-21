"""テンプレートが所有する固定表示・操作契約を検証するテスト。"""

from pathlib import Path
import re


def test_login_template_owns_fixed_form_labels() -> None:
    # 観点: ログインフォームの固定ラベルとplaceholderはテンプレート自身が持つこと。
    # 目的: HTTP routeテストで静的表示文言まで確認しない責務分離にする。
    source = _template("login.html")

    assert "{% block title %}Login{% endblock %}" in source
    assert '<label class="labelText" for="login_name">User ID</label>' in source
    assert '<label class="labelText" for="password">Password</label>' in source
    assert 'placeholder="User ID"' in source
    assert 'placeholder="Password"' in source
    assert ">Login</button>" in source


def test_initial_setup_template_is_distinct_from_login_template() -> None:
    # 観点: 初期管理者作成画面が初回専用であることを視覚・文言で強調すること。
    # 目的: ログイン画面と同じフォームに見えて操作を誤る状態を避ける。
    source = _template("setup_admin.html")

    assert 'class="setupBadge"' in source
    assert ">First-time setup</div>" in source
    assert "This setup is available only once." in source
    assert "border-top: 4px solid var(--accent);" in source


def test_chat_form_template_owns_composer_contract() -> None:
    # 観点: チャット入力欄の固定DOM契約はchat_formテンプレートが持つこと。
    # 目的: HTTP routeテストでは表示状態の変化だけを確認できるようにする。
    source = _template("chat_form.html")

    assert 'placeholder="Message"' in source
    assert "data-chat-composer" in source
    assert "data-chat-attachment-list" in source
    assert "data-chat-file-input" in source
    assert "data-chat-file-label" in source
    assert 'accept="{{ selected_file_accept }}"' in source
    assert "data-allowed-file-extensions" in source
    assert "data-chat-drop-hint" in source
    assert "data-chat-drop-extensions" in source
    assert re.search(r"\.dropHint\s*\{[^}]*flex-direction:\s*column", source, re.S) is None
    assert "data-chat-status" not in source
    assert 'class="attachmentRow"' not in source
    assert ">Attach file</span>" not in source


def test_chat_form_script_rejects_disallowed_files_and_supports_drop() -> None:
    # 観点: 添付UIのブラウザ側制御が選択・ドラッグアンドドロップ・貼り付けを扱うこと。
    # 目的: サーバー送信前にassistantごとの許可拡張子と同じ入口制御を行う。
    source = Path("src/static/js/chat/form.js").read_text(encoding="utf-8")

    assert "fileExtensionAllowed" in source
    assert "filterAllowedFiles" in source
    assert "refreshDropExtensions" in source
    assert "clipboardImageFiles" in source
    assert 'addEventListener("drop"' in source
    assert 'addEventListener("dragover"' in source
    assert 'addEventListener("paste"' in source


def test_chat_form_limits_attachments_and_shows_the_limit() -> None:
    # 観点: 11件以上を追加したとき、10件に制限して理由を画面へ表示すること。
    # 目的: サーバーの400だけで失敗し、送信が反映されないように見える状態を防ぐ。
    template = _template("chat_form.html")
    source = Path("src/static/js/chat/form.js").read_text(encoding="utf-8")

    assert 'data-chat-file-limit="10"' in template
    assert "data-chat-attachment-notice" in template
    assert 'role="alert"' in template
    assert "attachmentLimit" in source
    assert "allowedFiles.slice(0, availableSlots)" in source
    assert "Up to ${attachmentLimit} files can be attached." in source


def test_chat_stream_script_keeps_event_source_for_browser_reconnect() -> None:
    # 観点: 一時切断やlocal Jobを持たないworkerのSSE終了時に明示closeしないこと。
    # 目的: local Jobなしの再確認をserver pollingではなくブラウザ標準再接続へ委ねる。
    source = Path("src/static/js/chat/stream.js").read_text(encoding="utf-8")

    assert "source.readyState === EventSource.CLOSED" in source
    assert 'if (patch.error)' in source
    assert 'if (patch.done)' in source


def test_chat_form_tracks_processing_streams_by_message_id() -> None:
    # 観点: 初期processing表示とstream-startを同じmessageとして数えること。
    # 目的: 初期値と開始eventの二重加算で応答完了後も送信不能になる状態を防ぐ。
    source = Path("src/static/js/chat/form.js").read_text(encoding="utf-8")

    assert "new Set(" in source
    assert "activeProcessingMessageIds.add(messageId)" in source
    assert "activeProcessingMessageIds.delete(messageId)" in source


def test_message_list_owns_message_collection_structure() -> None:
    # 観点: メッセージ群の繰り返しと一覧内余白をmessage_listが一体で持つこと。
    # 目的: 中間テンプレートによる不要な包含関係を作らない。
    message_list = _template("message_list.html")
    message_item = _template("message_item.html")
    chat_form = _template("chat_form.html")

    assert "{% for msg in messages %}" in message_list
    assert 'include "message_items.html"' not in message_list
    assert "margin-bottom: .75rem;" in message_list
    assert ".messageItem:last-of-type" in message_list
    assert "message_items_only" not in message_list
    assert not Path("src/templates/message_items.html").exists()
    assert 'hx-swap="{% if thread %}beforeend{% else %}outerHTML{% endif %}"' in chat_form
    assert 'hx-select="#messages > .messageItem"' in chat_form
    assert ":scope {" in message_item
    assert ".messageBubble {" in message_item


def test_message_item_slowly_pulses_only_while_waiting_for_response() -> None:
    # 観点: AI応答の本文が届く前だけ、待機表示が緩やかに明滅すること。
    # 目的: 生成済み本文の可読性を損なわず、応答待ちであることを視覚的に伝える。
    source = _template("message_item.html")

    assert '.streaming .messageBubble[data-chat-raw-content=""]' in source
    assert "animation: waitingPulse 2.4s ease-in-out infinite;" in source
    assert "@keyframes waitingPulse" in source
    assert "@media (prefers-reduced-motion: reduce)" in source


def test_message_item_applies_user_presentation_to_the_scope_root() -> None:
    # 観点: スコープ根であるユーザーメッセージ自身に配置と配色の条件を適用すること。
    # 目的: @scope内の子孫セレクタだけになり、ユーザー表示がAI表示と同一になることを防ぐ。
    source = _template("message_item.html")

    assert ":scope.userMessage {" in source
    assert ":scope.assistantMessage {" in source
    assert ":scope.userMessage .messageBubble {" in source
    assert ":scope.assistantMessage .messageContent {" in source
    assert "max-width: 100%;" in source
    assert ":scope.userMessage .messageContent {" in source
    assert "max-width: min(100%, 46rem);" in source


def test_chat_form_template_groups_assistant_options() -> None:
    # 観点: assistant selectのoptgroupと説明併記はchat_formテンプレートが持つこと。
    # 目的: 選択肢データの並び規則とHTMLラベル表現を分離して固定する。
    source = _template("chat_form.html")

    assert '("Mine", owned_assistants)' in source
    assert '("System", system_assistants)' in source
    assert '("Shared", other_assistants)' in source
    assert "<optgroup label=\"{{ label }}\">" in source
    assert "{{ assistant.name }}{% if assistant.description %} - {{ assistant.description }}{% endif %}" in source


def test_user_assistant_form_template_owns_prompt_examples_and_fields() -> None:
    # 観点: 個人アシスタントフォームの固定入力項目は専用テンプレートが持つこと。
    # 目的: BaseAssistantフォームとの違いをHTTP統合テストから切り離す。
    source = _template("user_assistant_form.html")

    assert 'placeholder="Name"' in source
    assert 'placeholder="Description"' in source
    assert 'placeholder="例：短く返答します"' in source
    assert 'id="base_assistant_id" name="base_assistant_id" required' in source
    assert ">&lt;not set&gt;</option>" in source
    assert ">Private (owner only)</option>" in source
    assert ">Public (all users)</option>" in source
    assert 'name="visibility"' in source
    assert 'name="connection_provider_id"' not in source
    assert 'name="model"' not in source
    assert 'name="system_prompt"' not in source
    assert 'name="generation_config_json"' not in source
    assert "割り当てなし" not in source


def test_base_assistant_form_template_owns_prompt_examples_and_fields() -> None:
    # 観点: 基本アシスタントフォームの固定入力項目は専用テンプレートが持つこと。
    # 目的: 個人アシスタントフォームとの違いをHTTP統合テストから切り離す。
    source = _template("base_assistant_form.html")

    assert 'placeholder="Name"' in source
    assert 'placeholder="Description"' in source
    assert 'placeholder="例：機密情報は扱わない"' in source
    assert 'placeholder="例：短く返答します"' in source
    assert "placeholder='例：{\"temperature\": 0.2}'" in source
    assert 'name="allowed_file_extensions"' in source
    assert "jpg" in source
    assert "jpeg" in source
    assert "png" in source
    assert ">&lt;select&gt;</option>" in source
    assert 'name="connection_provider_id"' in source
    assert 'name="model"' in source
    assert 'name="system_prompt"' in source
    assert 'name="generation_config_json"' in source
    assert 'name="base_assistant_id"' not in source
    assert 'name="visibility"' not in source


def test_base_assistant_form_template_groups_editing_sections() -> None:
    # 観点: BaseAssistant編集フォームは利用者の認知単位ごとに設定を分けて表示すること。
    # 目的: 基本設定・プロンプト・詳細JSONが無秩序に並ぶ画面へ戻らないようにする。
    source = _template("base_assistant_form.html")

    assert '<section class="assistantFormSection assistantPrimarySection">' in source
    assert '<h2 class="sectionHeading">Basic settings</h2>' in source
    assert '<h2 class="sectionHeading">Prompts</h2>' in source
    assert '<section class="assistantFormSection assistantJsonSection">' in source
    assert '<h2 class="sectionHeading">Config JSON</h2>' in source
    assert "<details" not in source


def test_base_assistant_form_template_shows_provider_model_as_pair() -> None:
    # 観点: ProviderとModelは依存関係がある設定として隣接し一体に見えること。
    # 目的: 接続先を選んでからモデルを選ぶ操作順序をHTML構造で固定する。
    source = _template("base_assistant_form.html")

    assert '<div class="assistantProviderModelGroup">' in source
    assert source.index('id="connection_provider_id"') < source.index('id="model"')
    assert 'data-provider-model-select' in source


def test_base_assistant_form_template_uses_single_line_extension_input() -> None:
    # 観点: 許可拡張子は区切り方が分かる1行入力として表示すること。
    # 目的: 複数行テキスト欄により改行区切りかカンマ区切りか迷う状態を避ける。
    source = _template("base_assistant_form.html")

    assert (
        '<input class="inputField" id="allowed_file_extensions" '
        'name="allowed_file_extensions" value="{{ allowed_file_extensions_text }}" '
        'placeholder="png, jpg, jpeg, gif, webp, txt, md, pdf">'
    ) in source
    assert 'textarea class="inputField assistantExtensionArea"' not in source


def test_sidebar_template_owns_account_and_logout_display_contract() -> None:
    # 観点: サイドバーのアカウント表示とログアウト表示はテンプレートが持つこと。
    # 目的: route統合テストから静的なアイコン表示契約を分離する。
    source = _template("sidebar.html")

    assert "<span>New chat</span>" in source
    assert "<span>My Assistants</span>" in source
    assert "sidebarAccountPanel" in source
    assert "iconOnlyButton" in source
    assert 'title="Logout"' in source
    assert 'aria-label="Logout"' in source
    assert "<span>Logout</span>" not in source


def test_sidebar_includes_theme_switch_component() -> None:
    # 観点: サイドバーはテーマ切り替えの詳細を持たず専用テンプレートへ委譲すること。
    # 目的: テーマ切り替えのDOM・CSS・JSを一つのコンポーネントに閉じ込める。
    source = _template("sidebar.html")

    assert '{% include "theme_switch.html" %}' in source
    assert "sidebarThemeControl" not in source
    assert "data-theme-toggle" not in source


def test_theme_switch_template_owns_markup_style_and_behavior() -> None:
    # 観点: theme switchテンプレートだけで表示・装飾・横並び表示・切り替え処理が完結すること。
    # 目的: 利用箇所を増やしても関連実装が複数ファイルへ分散しないようにする。
    source = _template("theme_switch.html")

    assert "<style>" in source
    assert "@scope {" in source
    assert "<script>" in source
    assert "sidebarThemeControl" in source
    assert "width: 100%;" in source
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in source
    assert ":scope {" in source
    assert ".sidebarThemeButton {" in source
    assert 'data-theme-value="light"' in source
    assert 'data-theme-value="dark"' in source
    assert 'aria-pressed="true"' in source
    assert 'aria-pressed="false"' in source
    assert "fa-sun" in source
    assert "fa-moon" in source
    assert "chat.theme" in source
    assert "document.documentElement.dataset.theme" in source
    assert "window.localStorage.getItem" in source
    assert "window.localStorage.setItem" in source
    assert "try {" in source


def test_app_script_does_not_own_theme_switch_behavior() -> None:
    # 観点: 共通app scriptがtheme switch固有の処理を持たないこと。
    # 目的: コンポーネント分離後に二重イベント登録や初期化順依存を残さない。
    source = Path("src/static/js/app.js").read_text(encoding="utf-8")

    assert "mountThemeToggle" not in source
    assert "chat.theme" not in source
    assert "data-theme-toggle" not in source


def _template(name: str) -> str:
    return Path("src/templates", name).read_text(encoding="utf-8")
