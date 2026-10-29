"""
审计日志自动埋点中间件（移植自 VoxAudit）

职责：对所有非 GET 请求自动从 URL 推断 action / target_type / target_id，
      调 record_action(...) 写入审计日志。

设计原则：
- 拿不到业务上下文（中间件看不到路由函数里的变量）；关键接口（登录、改密、转写失败）
  仍在路由函数里手动 record_action(...) 以补充 detail。
- 推断规则：先用 FINE_RULES 精确匹配；未命中走 COARSE_FALLBACK 兜底。
- 仅记录 management 类动作 + 转写/生成/上传/删除；GET 查询接口一律跳过。
"""
from __future__ import annotations

import re
from fastapi import Request, Response
from loguru import logger

from backend.services.audit_service import record_action


# ——— 精确规则（meeting_copilot 路由）——
# 每条: (method, regex, action, target_type, id_group_name)
FINE_RULES: list[tuple[str, re.Pattern, str, str | None, str | None]] = [
    # —— 会议管理 ——
    ("POST",   re.compile(r"^/api/v1/meetings/init-upload$"),                       "meeting.init_upload",    None, None),
    ("POST",   re.compile(r"^/api/v1/meetings/(?P<id>[^/]+)/upload$"),              "meeting.upload",         "meeting", "id"),
    ("POST",   re.compile(r"^/api/v1/meetings/(?P<id>[^/]+)/minutes$"),             "meeting.generate_minutes", "meeting", "id"),
    ("DELETE", re.compile(r"^/api/v1/meetings/(?P<id>[^/]+)$"),                     "meeting.delete",         "meeting", "id"),
    # —— 系统设置 ——
    ("PUT",    re.compile(r"^/api/v1/settings/llm$"),                               "settings.update_llm",    None, None),
    ("PUT",    re.compile(r"^/api/v1/settings/asr$"),                               "settings.update_asr",    None, None),
    ("PUT",    re.compile(r"^/api/v1/settings/templates$"),                         "settings.update_template", None, None),
    ("DELETE", re.compile(r"^/api/v1/settings/templates/(?P<id>[^/]+)$"),           "settings.delete_template", "template", "id"),
    ("POST",   re.compile(r"^/api/v1/settings/llm/test$"),                           "settings.test",          None, None),
    ("POST",   re.compile(r"^/api/v1/settings/asr/test$"),                          "settings.test",          None, None),
]


# ——— 中间件跳过的路径前缀 ———
# 这些接口由路由函数手动 record_action(...) 写入更详细的审计行，
# 中间件跳过避免重复/丢失上下文。
_SKIP_PATH_PREFIXES = (
    "/api/v1/auth/",          # 登录/改密/登出：拿不到已认证用户，需手动记
    "/api/v1/admin/audit-logs/",  # 审计日志自身的写入入口，避免自审计
)


# ——— 粗粒度兜底：URL 第一段 → target_type；method → action 后缀 ——
_COARSE_TARGET_TYPE = {
    "meetings": "meeting",
    "settings": "settings",
    "transcript": None,  # GET only
    "asr": None,         # 走 FINE，不进兜底
}

_METHOD_TO_VERB = {
    "POST": "create",
    "PUT": "update",
    "DELETE": "delete",
    "PATCH": "update",
}


def _try_fine_rule(method: str, path: str) -> tuple[str | None, str | None, str | None]:
    """优先用精确规则匹配；返回 (action, target_type, target_id)"""
    for m, regex, action, target_type, id_group in FINE_RULES:
        if m != method:
            continue
        m_obj = regex.match(path)
        if not m_obj:
            continue
        target_id = m_obj.group(id_group) if id_group else None
        return action, target_type, target_id
    return None, None, None


def _coarse_fallback(method: str, path: str) -> tuple[str | None, str | None, str | None]:
    """未命中精确规则时的兜底：用 method + 第一段拼粗粒度 action"""
    if method not in _METHOD_TO_VERB:
        return None, None, None

    sub = path[len("/api/v1"):] if path.startswith("/api/v1") else path
    sub = sub.lstrip("/")
    if not sub:
        return None, None, None
    segments = sub.split("/")

    first = segments[0]
    target_type = _COARSE_TARGET_TYPE.get(first)
    target_id = segments[-1] if len(segments) > 1 else None

    action_verb = _METHOD_TO_VERB[method]
    if target_type:
        action = f"{target_type}.{action_verb}"
    else:
        action = action_verb

    return action, target_type, target_id


def _infer(method: str, path: str) -> tuple[str | None, str | None, str | None]:
    action, target_type, target_id = _try_fine_rule(method, path)
    if action:
        return action, target_type, target_id
    return _coarse_fallback(method, path)


async def _try_get_actor(request: Request) -> dict | None:
    """从 X-User-Info 头解出 actor（HMAC 签名 token）；失败返回 None"""
    try:
        from backend.core.auth_token import verify
        token = request.headers.get("x-user-info")
        if not token:
            return None
        return verify(token)
    except Exception:
        return None


async def audit_middleware(request: Request, call_next):
    """FastAPI 中间件：对所有非 GET 自动埋点审计日志"""
    method = request.method

    # 1) 先处理业务，拿到 response（确保不影响业务）
    response: Response = await call_next(request)

    # 2) GET / HEAD / OPTIONS 不记
    if method in ("GET", "HEAD", "OPTIONS"):
        return response

    # 3) 跳过静态资源/文档/健康检查
    path = request.url.path
    if path.startswith("/docs") or path.startswith("/openapi") or path == "/health":
        return response

    # 3.1) 跳过需要手动埋点的接口
    if any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
        return response

    # 4) 推断 action
    action, target_type, target_id = _infer(method, path)
    if not action:
        return response

    # 5) 取 actor（未登录则不记）
    actor = await _try_get_actor(request)
    if not actor:
        return response

    # 6) 写审计（异步、不阻塞 response）
    result = "success" if response.status_code < 400 else "fail"
    try:
        await record_action(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request=request,
            result=result,
        )
    except Exception as e:
        logger.warning(f"audit_middleware 写入失败: {e}")

    return response
