
"""ドメインや画面の要求に合わせた読み取り専用Queryを定義する。

CRUD Repositoryがテーブル単位の保存操作を持つのに対し、このファイルは
「チャット詳細」「アシスタント選択肢」のような利用側の読み取り形を返す。
"""

import sqlite3

from ..models import AssistantOption, Thread, ThreadDetail
from .base_assistant import BaseAssistantRepository
from .message import MessageRepository
from .thread import ThreadRepository
from .user_assistant import UserAssistantRepository


class ChatThreadQuery:
    """チャット表示に必要なThread読み取りを担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """SQLite connectionを受け取り、Queryを初期化する。

        Args:
            conn: 同一transactionで読み取るSQLite connection。

        Returns:
            None。

        CRUD Repositoryと同じ接続を共有し、service側でtransaction境界を選べるようにする。
        """
        self.conn = conn

    def list_sidebar_threads(self, user_id: int) -> list[Thread]:
        """サイドバー表示用の未削除Thread一覧を返す。

        Args:
            user_id: Thread所有者として絞り込むユーザーID。

        Returns:
            更新日時降順のThread一覧。

        画面名に寄せたQuery名にして、単なるテーブル一覧ではなく表示要求の読み取りと分かるようにする。
        """
        return ThreadRepository(self.conn).list_by_user(user_id)

    def get_detail_for_user(self, *, thread_id: str, user_id: int) -> ThreadDetail | None:
        """所有者検証済みThreadと配下Messageをまとめて返す。

        Args:
            thread_id: 詳細表示対象のThread ID。
            user_id: 所有者として検証するユーザーID。

        Returns:
            表示可能なThreadDetail。対象がない、または所有者でなければNone。

        route/serviceがThread取得とMessage取得の組み合わせ規則を重複して持たないよう、
        チャット詳細の読み取り形をここへ集約する。
        """
        thread = ThreadRepository(self.conn).get(thread_id, user_id)
        if thread is None:
            return None
        messages = MessageRepository(self.conn).list_by_thread(thread.id)
        return ThreadDetail(thread=thread, messages=messages)


class AssistantSelectionQuery:
    """チャットで選べるAssistant候補の読み取りを担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """SQLite connectionを受け取り、Queryを初期化する。

        Args:
            conn: 同一transactionで読み取るSQLite connection。

        Returns:
            None。

        BaseAssistantとUserAssistantを組み合わせる読み取りなので、CRUDとは別のQuery入口にする。
        """
        self.conn = conn

    def list_chat_options(self, user_id: int) -> list[AssistantOption]:
        """チャット投稿フォームで選択できるAssistantOptionを返す。

        Args:
            user_id: 選択肢を見るユーザーID。

        Returns:
            所有UserAssistant、BaseAssistant、他者public UserAssistantの順に並ぶ選択肢。

        BaseAssistant削除済みのUserAssistantは実行できないため除外し、
        添付許可は実行元BaseAssistantの設定から読む。
        """
        base_repo = BaseAssistantRepository(self.conn)
        user_repo = UserAssistantRepository(self.conn)
        base_assistants = base_repo.list_active()
        user_assistants = user_repo.list_available(user_id)
        system_options = [
            AssistantOption(
                id=assistant.id,
                name=assistant.name,
                description=assistant.description,
                allow_file_upload=assistant.allow_file_upload,
                kind="base",
                category="system_public",
                allowed_file_extensions=assistant.allowed_file_extensions,
            )
            for assistant in base_assistants
        ]
        owned_options: list[AssistantOption] = []
        other_public_options: list[AssistantOption] = []
        for assistant in user_assistants:
            base = (
                base_repo.get(assistant.base_assistant_id)
                if assistant.base_assistant_id
                else None
            )
            if base is None:
                continue
            option = AssistantOption(
                id=assistant.id,
                name=assistant.name,
                description=assistant.description,
                allow_file_upload=base.allow_file_upload,
                kind="user",
                category=(
                    "owned"
                    if assistant.owner_user_id == user_id
                    else "other_public"
                ),
                allowed_file_extensions=base.allowed_file_extensions,
            )
            if assistant.owner_user_id == user_id:
                owned_options.append(option)
            else:
                other_public_options.append(option)
        return [*owned_options, *system_options, *other_public_options]


__all__ = ["AssistantSelectionQuery", "ChatThreadQuery"]
