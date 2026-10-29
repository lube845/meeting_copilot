"""
安全工具：PBKDF2 密码哈希（参照 VoxAudit，使用 stdlib hashlib 不引入 bcrypt）
"""
import secrets
import hashlib

_PBKDF2_ITERATIONS = 120_000
_PBKDF2_ALGO = "sha256"


def hash_password(password: str) -> tuple[str, str]:
    """生成 (salt_hex, hash_hex)。"""
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return salt.hex(), h.hex()


def verify_password(password: str, salt_hex: str, expected_hash_hex: str) -> bool:
    h = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERATIONS)
    return secrets.compare_digest(h.hex(), expected_hash_hex)