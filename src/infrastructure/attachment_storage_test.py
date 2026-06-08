"""添付ファイル実体ストレージの保存・取得境界を検証する。"""

import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
import pytest
from starlette.datastructures import Headers

from src.infrastructure.attachment_storage import AttachmentStorage
from src.models import PendingUpload, UserInputError


def test_attachment_storage_accepts_configured_file_extension(
    tmp_path: Path,
) -> None:
    # 観点: 設定で許可された拡張子のファイルだけを保存できること。
    # 目的: 添付種別ごとの入口判定をストレージ境界へ集約する。
    storage = AttachmentStorage(
        tmp_path,
        allowed_file_extensions={"image": ["png", "jpg"], "text": ["txt", "md"]},
    )
    upload = UploadFile(
        BytesIO(b"hello"),
        filename="memo.md",
        headers=Headers({"content-type": "text/markdown"}),
    )

    saved = asyncio.run(storage.save(user_id=1, upload=_pending_upload(upload)))

    assert saved.original_filename == "memo.md"
    assert storage.resolve(saved.stored_path).read_bytes() == b"hello"


def test_attachment_storage_rejects_unconfigured_file_extension(
    tmp_path: Path,
) -> None:
    # 観点: 設定にない拡張子は保存前に拒否すること。
    # 目的: 未対応ファイルをディスクやDBへ持ち込まない境界を固定する。
    storage = AttachmentStorage(
        tmp_path,
        allowed_file_extensions={"image": ["png"], "pdf": ["pdf"]},
    )
    upload = UploadFile(
        BytesIO(b"binary"),
        filename="archive.zip",
        headers=Headers({"content-type": "application/zip"}),
    )

    with pytest.raises(UserInputError):
        asyncio.run(storage.save(user_id=1, upload=_pending_upload(upload)))


def test_attachment_storage_rejects_path_escape(tmp_path: Path) -> None:
    # 観点: 保存相対パスがuploads_dirの外へ出られないこと。
    # 目的: ダウンロードや削除処理が安全なパス解決だけに依存できるようにする。
    storage = AttachmentStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.resolve("../outside.txt")


def _pending_upload(upload: UploadFile) -> PendingUpload:
    """テスト用UploadFileをアプリ内入力境界へ変換する。"""
    return PendingUpload(
        filename=upload.filename or "",
        content_type=upload.content_type or "",
        read=upload.read,
        close=upload.close,
    )
