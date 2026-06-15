"""添付ファイル実体の保存、取得、パス解決を担当する。

DB metadata は AttachmentRepository に任せ、このモジュールは uploads_dir 配下の
ファイル実体だけを扱う。HTTP route や usecase からは repository 風の境界として
利用できるよう、保存と安全な実パス解決を提供する。
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..models import PendingUpload, UserInputError, normalize_file_extensions

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 5
AllowedFileExtensions = dict[str, list[str]]
DEFAULT_ALLOWED_FILE_EXTENSIONS: AllowedFileExtensions = {
    "image": ["png", "jpg", "jpeg", "gif", "webp"],
    "text": ["txt", "md"],
    "pdf": ["pdf"],
}


@dataclass(frozen=True)
class UploadedAttachment:
    """ファイル保存後にDBへ登録するmetadataを表す。"""

    original_filename: str
    stored_path: str
    content_type: str
    size_bytes: int
    sha256: str


class AttachmentStorage:
    """uploads_dir配下へのファイル保存と安全なパス解決を担当する。"""

    def __init__(
        self,
        uploads_dir: Path,
        allowed_file_extensions: AllowedFileExtensions | None = None,
    ) -> None:
        """AttachmentStorageを作成する。

        Args:
            uploads_dir: 添付ファイルの保存先ルート。
            allowed_file_extensions: 種別名ごとの許可拡張子一覧。

        Returns:
            None。

        保存可能な拡張子を初期化時に正規化し、保存処理の判定を単純にする。
        """
        self.uploads_dir = uploads_dir
        self.allowed_extensions = _normalize_allowed_extensions(
            allowed_file_extensions or DEFAULT_ALLOWED_FILE_EXTENSIONS
        )

    async def save(
        self,
        *,
        user_id: int,
        upload: PendingUpload,
        allowed_file_extensions: list[str] | None = None,
    ) -> UploadedAttachment:
        """未保存アップロードをディスクへ保存し、保存metadataを返す。

        Args:
            user_id: 保存先を分離するログインユーザーID。
            upload: presentation層でFastAPI型から変換した未保存アップロード。
            allowed_file_extensions: この保存で許可するdotなし拡張子一覧。

        Returns:
            DBへ登録するための保存metadata。

        Raises:
            UserInputError: 拡張子未許可、空ファイル、サイズ超過の場合。

        route がファイルストリームの読み書きやハッシュ計算を知らずに済むよう、
        保存実体に関する処理をこの境界へ閉じ込める。
        """
        filename = Path(upload.filename or "upload").name
        allowed_extensions = (
            set(normalize_file_extensions(allowed_file_extensions))
            if allowed_file_extensions is not None
            else self.allowed_extensions
        )
        if not _extension_is_allowed(filename, allowed_extensions):
            raise UserInputError("file extension is not allowed")
        safe_name = _safe_filename(filename)
        relative_path = Path(str(user_id)) / f"{uuid4().hex}_{safe_name}"
        destination = self.uploads_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        size = 0
        with destination.open("wb") as fp:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES:
                    destination.unlink(missing_ok=True)
                    raise UserInputError("attachment is too large")
                digest.update(chunk)
                fp.write(chunk)
        await upload.close()
        if size == 0:
            destination.unlink(missing_ok=True)
            raise UserInputError("attachment is empty")

        return UploadedAttachment(
            original_filename=filename,
            stored_path=relative_path.as_posix(),
            content_type=upload.content_type or "application/octet-stream",
            size_bytes=size,
            sha256=digest.hexdigest(),
        )

    def resolve(self, stored_path: str) -> Path:
        """保存相対パスをuploads_dir配下の実パスへ安全に変換する。

        Args:
            stored_path: DB metadata に保持している uploads_dir 相対パス。

        Returns:
            uploads_dir 配下に解決済みの実パス。

        Raises:
            ValueError: 相対パスが uploads_dir の外へ出る場合。

        ダウンロードや削除処理が任意パスを触らないよう、実ファイル取得前に
        ルート配下であることを検証する。
        """
        path = (self.uploads_dir / stored_path).resolve()
        root = self.uploads_dir.resolve()
        if root != path and root not in path.parents:
            raise ValueError("invalid attachment path")
        return path

    def delete(self, stored_path: str) -> None:
        """保存相対パスに対応する実ファイルを削除する。

        Args:
            stored_path: DB metadata に保持している uploads_dir 相対パス。

        Returns:
            None。

        安全なパス解決と存在しないファイルの扱いをストレージ境界へ閉じ込め、
        usecaseがファイルシステムの詳細を持たずに補償処理を行えるようにする。
        """
        self.resolve(stored_path).unlink(missing_ok=True)


def _safe_filename(filename: str) -> str:
    """保存ファイル名に使えるASCII文字へ正規化する。

    Args:
        filename: 利用者がアップロードした元ファイル名。

    Returns:
        保存ファイル名へ埋め込める安全なファイル名。

    ユーザー入力をそのままファイル名に使わず、OS差や表示崩れを避けるため。
    """
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return name or "upload"


def _normalize_allowed_extensions(
    allowed_file_extensions: AllowedFileExtensions,
) -> set[str]:
    """設定された拡張子一覧を大小文字や先頭dotに依存しないsetへ変換する。

    Args:
        allowed_file_extensions: 種別名ごとの許可拡張子一覧。

    Returns:
        dotなし小文字の拡張子set。

    設定表記の揺れで保存可否が変わらないようにする。
    """
    return {
        extension.lower().lstrip(".")
        for extensions in allowed_file_extensions.values()
        for extension in extensions
        if extension.strip()
    }


def _extension_is_allowed(filename: str, allowed_extensions: set[str]) -> bool:
    """ファイル名の拡張子が許可setに含まれるか判定する。

    Args:
        filename: 利用者がアップロードした元ファイル名。
        allowed_extensions: dotなし小文字の許可拡張子set。

    Returns:
        許可される拡張子ならTrue。

    content-type はクライアント由来で揺れるため、保存入口では設定された拡張子を
    明示的な許可条件として使う。
    """
    extension = Path(filename).suffix.lower().lstrip(".")
    return bool(extension and extension in allowed_extensions)


__all__ = [
    "AllowedFileExtensions",
    "AttachmentStorage",
    "DEFAULT_ALLOWED_FILE_EXTENSIONS",
    "MAX_ATTACHMENT_BYTES",
    "MAX_ATTACHMENTS_PER_MESSAGE",
    "UploadedAttachment",
]
