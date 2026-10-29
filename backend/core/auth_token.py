"""
HMAC 签名的会话令牌（替换旧版「裸 base64 user_info」）

格式：v1.<base64url(payload)>.<hex(hmac_sha256)>

设计要点：
- 服务端签名 → 客户端无法独立篡改 loginid / is_admin / login_time / exp
- 使用 settings.AUTH_SECRET（启动时必填）
- 解析失败 / 签名错 / 已过期统一返回 None，由调用方 401
"""
import base64
import hashlib
import hmac
import json
from typing import Optional

from loguru import logger

from backend.core.config import settings

_TOKEN_VERSION = "v1"
_ALGO = hashlib.sha256


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload_bytes: bytes) -> str:
    return hmac.new(
        settings.AUTH_SECRET.encode("utf-8"),
        payload_bytes,
        _ALGO,
    ).hexdigest()


def sign(payload: dict) -> str:
    """签名 payload（dict）→ 返回 v1.<b64>.<sig>"""
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = _b64encode(raw).encode("ascii")
    sig = _sign(body)
    return f"{_TOKEN_VERSION}.{body.decode('ascii')}.{sig}"


def verify(token: str) -> Optional[dict]:
    """校验签名 + 过期；返回 payload 或 None"""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_VERSION:
        return None
    _, b64, sig = parts
    try:
        body = b64.encode("ascii")
        if not hmac.compare_digest(_sign(body), sig):
            logger.warning("auth_token: 签名校验失败")
            return None
        raw = _b64decode(b64)
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        logger.warning(f"auth_token: 解析失败 {e}")
        return None

    # 过期校验（用 payload 里的 exp 字段，不再信任客户端 login_time）
    import time
    exp = payload.get("exp")
    if exp and time.time() > float(exp):
        logger.info("auth_token: 已过期")
        return None

    return payload