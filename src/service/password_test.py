"""パスワードのハッシュ化と照合を行うserviceの契約を検証する。"""

from src.service.password import hash_password, verify_password


def test_hash_password_creates_salted_hash_that_can_be_verified() -> None:
    # 観点: 同じパスワードからsalt付きハッシュを生成し、正しい入力だけ照合できること。
    # 目的: 平文を保存せず、認証に利用できるハッシュ生成・照合契約を固定する。
    first_hash = hash_password("adminpass", "pepper")
    second_hash = hash_password("adminpass", "pepper")

    assert first_hash != second_hash
    assert first_hash.startswith("pbkdf2_sha256$")
    assert verify_password("adminpass", first_hash, "pepper") is True
    assert verify_password("wrongpass", first_hash, "pepper") is False


def test_verify_password_rejects_invalid_hash_format() -> None:
    # 観点: 保存済みハッシュが不正形式でも例外を外へ漏らさないこと。
    # 目的: 認証失敗として安全に扱うservice境界を固定する。
    assert verify_password("adminpass", "invalid-hash", "pepper") is False
