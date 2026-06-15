"""認証で使うパスワードのハッシュ化と照合を担当する。"""

import hashlib
import hmac
import secrets

PASSWORD_HASH_ITERATIONS = 210_000


def hash_password(password: str, pepper: str) -> str:
    """平文パスワードを保存用ハッシュ文字列へ変換する。

    Args:
        password: 平文パスワード。
        pepper: アプリ全体で共有する秘密値。

    Returns:
        salt と digest を含む保存用ハッシュ文字列。
    """
    salt = secrets.token_bytes(16)
    digest = _password_digest(password=password, pepper=pepper, salt=salt)
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str, pepper: str) -> bool:
    """平文パスワードが保存済みハッシュと一致するか検証する。

    Args:
        password: 入力された平文パスワード。
        password_hash: DB に保存されたハッシュ文字列。
        pepper: アプリ全体で共有する秘密値。

    Returns:
        一致時はTrue、不一致または形式不正時はFalse。
    """
    try:
        algorithm, iterations, salt_hex, digest_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256" or int(iterations) != PASSWORD_HASH_ITERATIONS:
            return False
        expected = bytes.fromhex(digest_hex)
        digest = _password_digest(
            password=password,
            pepper=pepper,
            salt=bytes.fromhex(salt_hex),
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)


def _password_digest(password: str, pepper: str, salt: bytes) -> bytes:
    """パスワード、pepper、saltからPBKDF2 digestを生成する。

    Args:
        password: digest生成対象の平文パスワード。
        pepper: アプリ全体で共有する秘密値。
        salt: ハッシュごとに生成するランダム値。

    Returns:
        SHA-256を使ったPBKDF2 digest。

    ハッシュ生成と照合で同じ導出処理を共有し、保存形式の差異を防ぐ。
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        f"{password}:{pepper}".encode(),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
