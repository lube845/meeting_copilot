"""
OA 免登录/代填认证模块（移植自 VoxAudit，去掉 k 账号分流）

与 OA 系统的两个接口：
1. POST /api/hrm/login/checkLogin              —— 校验工号 + 密码
2. POST /api/hrm/resful/getHrmUserInfoWithPage —— 按工号查询员工信息

设计：
- OA 只负责「认证 + 提供员工信息」；账号的本地建档、角色（is_admin）仍由本地
  users 表管理（见 backend/api/auth.py），这样权限模型只有一处真相。
- 全部用 httpx.AsyncClient 异步调用，不阻塞事件循环。
- OA 未配置（OA_BASE_URL 为空）时，调用方应跳过 OA 路径走本地登录。
"""
import asyncio
from typing import Optional, Tuple

import httpx
from loguru import logger

from backend.core.config import settings


# ——— OA 响应里我们关心的字段（中文 key → 内部用途）——
# VoxAudit 用的是 OA 返回的原始中文字段名，这里保持一致，便于对账。
_FIELD_MAP = {
    "workcode": "工号",
    "lastname": "姓名",
    "departmentname": "部门",
    "loginid": "loginid",
    "subcompanyname": "分部",
    "jobtitle": "岗位",
    "email": "邮箱",
    "mobile": "手机",
    "status": "状态",
}


async def get_user_info_from_oa(loginid: str) -> Optional[dict]:
    """按工号查询 OA 员工信息；查不到返回 None

    该接口已在 OA 侧设白名单，无需 token。
    """
    base_url = settings.OA_BASE_URL.rstrip("/")
    url = f"{base_url}/api/hrm/resful/getHrmUserInfoWithPage"
    payload = {"params": {"pagesize": 1, "workcode": loginid}}

    try:
        async with httpx.AsyncClient(timeout=settings.OA_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            result = resp.json()
    except httpx.TimeoutException:
        logger.warning(f"[OA] 查询用户信息超时: {loginid}")
        return None
    except Exception as e:
        logger.warning(f"[OA] 查询用户信息失败: {loginid} -> {e}")
        return None

    try:
        if result.get("code") != "1":
            logger.warning(f"[OA] 接口返回失败: {result.get('code')} {result.get('msg')}")
            return None
        user_list = result.get("data", {}).get("dataList", [])
        if not user_list:
            logger.info(f"[OA] 未找到用户: {loginid}")
            return None
        user = user_list[0]
        info = {
            "工号": user.get("workcode") or loginid,
            "姓名": user.get("lastname") or "未知",
            "部门": user.get("departmentname") or "",
            "loginid": user.get("loginid") or loginid,
            "分部": user.get("subcompanyname") or "",
            "岗位": user.get("jobtitle") or "",
            "邮箱": user.get("email") or "",
            "手机": user.get("mobile") or "",
            "状态": user.get("status") or "",
        }
        logger.info(f"[OA] 获取用户信息成功: {info['姓名']} ({info['部门']})")
        return info
    except Exception as e:
        logger.warning(f"[OA] 解析用户信息失败: {e}")
        return None


async def oa_login_with_password(loginid: str, password: str) -> Tuple[bool, Optional[dict], str]:
    """用工号 + 密码走 OA 校验

    Returns:
        (success, user_info, message)
    """
    base_url = settings.OA_BASE_URL.rstrip("/")
    login_url = f"{base_url}/api/hrm/login/checkLogin"
    payload = {
        "loginid": loginid,
        "userpassword": password,
        "logintype": "1",
        "islangueid": "7",
        "isRememberPassword": "false",
        "validatecode": "",
        "validateCodeKey": "",
        "dynamicPassword": "",
        "messages": "",
        "isie": "false",
        "appid": "",
        "service": "",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}

    try:
        async with httpx.AsyncClient(timeout=settings.OA_TIMEOUT) as client:
            login_resp = await client.post(login_url, data=payload, headers=headers)
            login_resp.raise_for_status()
            result = login_resp.json()
    except httpx.TimeoutException:
        return False, None, "OA 登录接口请求超时，请稍后重试"
    except Exception as e:
        logger.warning(f"[OA] 登录接口请求失败: {e}")
        return False, None, f"OA 登录接口请求失败: {e}"

    # checkLogin 成功时返回 loginstatus="true" 或 msgcode="0" 或 code="1"
    login_ok = (
        str(result.get("loginstatus")).lower() == "true"
        or str(result.get("msgcode")) == "0"
        or str(result.get("code")) == "1"
    )
    if not login_ok:
        msg = result.get("msg") or result.get("message") or "账号或密码错误"
        return False, None, msg

    user_info = await get_user_info_from_oa(loginid)
    if user_info is None:
        return False, None, "登录成功但无法获取员工信息，请联系管理员"

    return True, user_info, "登录成功"


def oa_enabled() -> bool:
    """是否配置了 OA 地址（未配置时登录应直接走本地账号）"""
    return bool(settings.OA_BASE_URL and not settings.OA_BASE_URL.startswith("<"))
