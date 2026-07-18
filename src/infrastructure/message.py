
"""Message集約とMessageKind永続化を担当する。"""

import sqlite3

from ..models import Message, MessageKind, MessageRole, MessageStatus
from .common import parse_dt, utcnow


def text_content(kinds: list[MessageKind]) -> str:
    for kind in kinds:
        if kind.kind == "text":
            return kind.content
    return ""


def model_from_row(
    row: sqlite3.Row,
    kinds_by_message_id: dict[int, list[MessageKind]],
) -> Message:
    message_id = int(row["id"])
    kinds = kinds_by_message_id.get(message_id, [])
    return Message(
        id=message_id,
        thread_id=row["thread_id"],
        role=MessageRole(row["role"]),
        content=text_content(kinds),
        status=MessageStatus(row["status"]),
        assistant_id=row["assistant_id"],
        kinds=kinds,
        created_at=parse_dt(row["created_at"]),
        updated_at=parse_dt(row["updated_at"]),
    )


def row_from_model(message: Message) -> dict[str, object]:
    return dict(
        id=message.id,
        thread_id=message.thread_id,
        role=message.role.value,
        status=message.status.value,
        assistant_id=message.assistant_id,
        created_at=message.created_at.isoformat(),
        updated_at=message.updated_at.isoformat(),
    )


def kind_rows_from_message(message: Message, *, created_at: str) -> list[dict[str, object]]:
    text_kind = MessageKind(kind="text", content=message.content, order_index=0)
    extra_kinds = [kind for kind in message.kinds if kind.kind != "text"]
    kinds = [text_kind] + [
        MessageKind(
            kind=item.kind,
            content=item.content,
            order_index=index,
            metadata_json=item.metadata_json,
        )
        for index, item in enumerate(extra_kinds, start=1)
    ]
    return [
        dict(
            message_id=message.id,
            order_index=kind.order_index,
            kind=kind.kind,
            content=kind.content,
            metadata_json=kind.metadata_json,
            created_at=created_at,
        )
        for kind in kinds
    ]


def kind_model_from_row(row: sqlite3.Row) -> MessageKind:
    return MessageKind(
        id=int(row["id"]),
        kind=row["kind"],
        content=row["content"],
        order_index=int(row["order_index"]),
        metadata_json=row["metadata_json"],
    )


def id_filter_values(
    values: list[int],
    *,
    prefix: str,
) -> tuple[str, dict[str, object]]:
    names: list[str] = []
    params: dict[str, object] = {}
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        names.append(f":{key}")
        params[key] = value
    return ", ".join(names), params


class MessageRepository:
    """Messageの保存・復元・状態収束を担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, message: Message) -> Message:
        row = row_from_model(message)
        if message.id > 0:
            self.conn.execute(
                """
                insert into messages(
                    id,
                    thread_id,
                    role,
                    status,
                    assistant_id,
                    created_at,
                    updated_at
                )
                values(
                    :id,
                    :thread_id,
                    :role,
                    :status,
                    :assistant_id,
                    :created_at,
                    :updated_at
                )
                """,
                row,
            )
            message_id = message.id
        else:
            cursor = self.conn.execute(
                """
                insert into messages(
                    thread_id,
                    role,
                    status,
                    assistant_id,
                    created_at,
                    updated_at
                )
                values(
                    :thread_id,
                    :role,
                    :status,
                    :assistant_id,
                    :created_at,
                    :updated_at
                )
                """,
                dict(
                    thread_id=message.thread_id,
                    role=message.role.value,
                    status=message.status.value,
                    assistant_id=message.assistant_id,
                    created_at=message.created_at.isoformat(),
                    updated_at=message.updated_at.isoformat(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create message")
            message_id = int(cursor.lastrowid)
        stored = Message(
            id=message_id,
            thread_id=message.thread_id,
            role=message.role,
            content=message.content,
            status=message.status,
            assistant_id=message.assistant_id,
            created_at=message.created_at,
            updated_at=message.updated_at,
            kinds=message.kinds,
        )
        self._insert_kinds(
            kind_rows_from_message(
                stored,
                created_at=message.created_at.isoformat(),
            )
        )
        return self.get(message_id)

    def update(self, message: Message) -> Message:
        self.conn.execute(
            """
            update messages set
                status = :status,
                assistant_id = :assistant_id,
                updated_at = :updated_at
            where
                id = :id
            """,
            dict(
                id=message.id,
                status=message.status.value,
                assistant_id=message.assistant_id,
                updated_at=message.updated_at.isoformat(),
            ),
        )
        self.conn.execute(
            """
            delete from
                message_kinds
            where
                message_id = :message_id
            """,
            dict(message_id=message.id),
        )
        self._insert_kinds(
            kind_rows_from_message(
                message,
                created_at=message.updated_at.isoformat(),
            )
        )
        return self.get(message.id)

    def update_processing_to_terminal(self, message: Message) -> Message | None:
        """processing messageをterminal状態へ条件付き更新する。

        Args:
            message: completedまたはfailedへ更新するassistant message。

        Returns:
            更新後または既に確定済みのMessage。対象が存在しなければNone。

        応答完了やcancelなどが競合しても、最初にprocessingから遷移した
        結果だけを永続化し、後着の結果でterminal状態を上書きしないために使う。
        commitは呼出し側の責務とする。

        Raises:
            ValueError: terminal以外のstatusを渡した場合。
        """
        if message.status not in {MessageStatus.COMPLETED, MessageStatus.FAILED}:
            raise ValueError("message status must be terminal")
        cursor = self.conn.execute(
            """
            update messages set
                status = :status,
                assistant_id = :assistant_id,
                updated_at = :updated_at
            where
                    id = :id
                and status = :processing_status
            """,
            dict(
                id=message.id,
                status=message.status.value,
                assistant_id=message.assistant_id,
                updated_at=message.updated_at.isoformat(),
                processing_status=MessageStatus.PROCESSING.value,
            ),
        )
        if cursor.rowcount != 1:
            # 0件は欠落だけでなく、cancelや別workerが先にterminalへ確定した
            # 場合も含む。後着側へDB上の勝者を返し、古いprocessing snapshotを
            # terminal結果として扱わせない。
            try:
                return self.get(message.id)
            except KeyError:
                return None
        # status更新に勝った処理だけが本文・reasoningも置換する。
        # 後着処理が先勝ちしたterminal snapshotを部分的に上書きしないため。
        self.conn.execute(
            """
            delete from
                message_kinds
            where
                message_id = :message_id
            """,
            dict(message_id=message.id),
        )
        self._insert_kinds(
            kind_rows_from_message(
                message,
                created_at=message.updated_at.isoformat(),
            )
        )
        return self.get(message.id)

    def fail_processing_assistant_messages(self) -> int:
        """再起動後のprocessing assistant messageをfailedへ収束させる。

        Returns:
            failedへ更新したmessage数。

        Job所有権を永続化していないため、この一括更新は正式サポートする
        単一workerの起動時だけ安全である。複数workerでは別processが生成中の
        messageまで更新し得るため使用しない。
        """
        now = utcnow().isoformat()
        cursor = self.conn.execute(
            """
            update messages set
                status = :status,
                updated_at = :updated_at
            where
                    role = :role
                and status = :processing_status
            """,
            dict(
                status=MessageStatus.FAILED.value,
                updated_at=now,
                role=MessageRole.ASSISTANT.value,
                processing_status=MessageStatus.PROCESSING.value,
            ),
        )
        return cursor.rowcount

    def get(self, message_id: int) -> Message:
        row = self.conn.execute(
            """
            select * from
                messages
            where
                id = :id
            """,
            dict(id=message_id),
        ).fetchone()
        if row is None:
            raise KeyError(message_id)
        return model_from_row(
            row,
            self._list_kinds_by_message_ids([message_id]),
        )

    def list_by_thread(self, thread_id: str) -> list[Message]:
        rows = self.conn.execute(
            """
            select * from
                messages
            where
                thread_id = :thread_id
            order by
                created_at asc
            """,
            dict(thread_id=thread_id),
        ).fetchall()
        message_ids = [int(row["id"]) for row in rows]
        kinds_by_message_id = self._list_kinds_by_message_ids(message_ids)
        return [model_from_row(row, kinds_by_message_id) for row in rows]

    def delete(self, message_id: int) -> bool:
        self.conn.execute(
            """
            delete from
                message_kinds
            where
                message_id = :message_id
            """,
            dict(message_id=message_id),
        )
        cursor = self.conn.execute(
            """
            delete from
                messages
            where
                id = :id
            """,
            dict(id=message_id),
        )
        return cursor.rowcount > 0

    def _insert_kinds(self, kind_rows: list[dict[str, object]]) -> None:
        for row in kind_rows:
            self.conn.execute(
                """
                insert into message_kinds(
                    message_id,
                    order_index,
                    kind,
                    content,
                    metadata_json,
                    created_at
                )
                values(
                    :message_id,
                    :order_index,
                    :kind,
                    :content,
                    :metadata_json,
                    :created_at
                )
                """,
                row,
            )

    def _list_kinds_by_message_ids(
        self, message_ids: list[int]
    ) -> dict[int, list[MessageKind]]:
        if not message_ids:
            return {}
        placeholders, id_params = id_filter_values(message_ids, prefix="message_id")
        rows = self.conn.execute(
            f"""
            select
                id,
                message_id,
                order_index,
                kind,
                content,
                metadata_json
            from
                message_kinds
            where
                message_id in ({placeholders})
            order by
                message_id asc,
                order_index asc
            """,
            id_params,
        ).fetchall()
        kinds_by_message_id: dict[int, list[MessageKind]] = {
            message_id: [] for message_id in message_ids
        }
        for row in rows:
            message_id = int(row["message_id"])
            kinds_by_message_id.setdefault(message_id, []).append(
                kind_model_from_row(row)
            )
        return kinds_by_message_id


__all__ = ["MessageRepository"]
