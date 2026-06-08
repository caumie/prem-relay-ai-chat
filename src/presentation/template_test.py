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
        'placeholder="jpg, jpeg, png">'
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


def _template(name: str) -> str:
    return Path("src/templates", name).read_text(encoding="utf-8")
