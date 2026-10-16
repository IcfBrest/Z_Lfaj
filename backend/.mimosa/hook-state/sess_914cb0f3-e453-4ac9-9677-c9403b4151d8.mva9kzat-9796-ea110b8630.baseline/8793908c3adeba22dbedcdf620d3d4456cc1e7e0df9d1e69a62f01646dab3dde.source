from app.security import decrypt_text, encrypt_text, hash_password, mask_secret, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-password")
    assert stored != "s3cret-password"
    assert verify_password("s3cret-password", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("s3cret-password", "garbage")


def test_fernet_roundtrip():
    cipher = encrypt_text("姓名：张三 13800138000")
    assert cipher != "姓名：张三 13800138000"
    assert decrypt_text(cipher) == "姓名：张三 13800138000"


def test_mask_secret():
    assert mask_secret("sk-abcdef123456") == "sk-a***"
    assert mask_secret("ab") == "***"
