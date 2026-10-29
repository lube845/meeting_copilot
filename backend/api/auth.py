"""
登录认证API

账号来源有两种（users.auth_source）：
- local：本地账号，密码用本地 PBKDF2 校验（seed 出来的 admin 兼底）
- oa   ：OA 账号，密码由 OA 校验；首次登录自动在本地建档（不存密码）

会话令牌统一用 HMAC 签名（backend/core/auth_token.py），客户端不可篡改。
"""
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.datetime_utils import get_current_time
from backend.core.security import hash_password, verify_password
from backend.core.auth_token import sign as sign_token, verify as verify_token
from backend.models.user import User
from backend.oa_auth import oa_enabled, oa_login_with_password
from backend.services.audit_service import record_action

router = APIRouter(prefix="/auth", tags=["认证"])


# ============ Schemas ============

class LoginRequest(BaseModel):
    loginid: str
    password: str


class UserInfo(BaseModel):
    loginid: str
    姓名: Optional[str] = None
    部门: Optional[str] = None
    岗位: Optional[str] = None
    is_admin: bool = False
    must_change_password: bool = False
    auth_source: str = "local"   # local / oa，用于审计角色识别


class LoginResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None  # HMAC 签名后的会话令牌（前端存到 localStorage）
    user_info: Optional[UserInfo] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ChangePasswordResponse(BaseModel):
    success: bool
    message: str


# ============ 当前用户依赖 ============

async def get_current_user(
    x_user_info: Optional[str] = Header(None, alias="X-User-Info"),
) -> dict:
    """从 X-User-Info 头解出 HMAC 签名后的 token；过期/无效则 401"""
    if not x_user_info:
        raise HTTPException(status_code=401, detail="请先登录")

    payload = verify_token(x_user_info)
    if not payload:
        raise HTTPException(status_code=401, detail="无效的用户信息或会话已过期")
    if not payload.get("loginid"):
        raise HTTPException(status_code=401, detail="无效的用户信息")

    return payload


async def get_current_user_required(
    user_info: dict = Depends(get_current_user),
) -> dict:
    """必须登录（路由的 function 内部显式调用）"""
    return user_info


async def require_admin(
    user_info: dict = Depends(get_current_user),
) -> dict:
    """必须登录且是管理员，否则 401/403（写类接口使用；读类接口仍只需登录）

    FastAPI 会按请求缓存同一个依赖的结果，因此这里内嵌的 get_current_user
    与路由级 dependencies 中的 get_current_user 只会验签一次。
    """
    if not user_info.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return user_info


# ============ 接口 ============

def _issue_token(user: User) -> str:
    """签发 HMAC 签名会话令牌（本地账号与 OA 账号共用）

    payload 里带 auth_source，审计中间件据此区分角色（local / oa）。
    """
    login_time = time.time()
    payload = {
        "loginid": user.loginid,
        "is_admin": bool(user.is_admin),
        "auth_source": user.auth_source or "local",
        "login_time": login_time,
        "exp": login_time + settings.SESSION_EXPIRE_HOURS * 3600,
    }
    return sign_token(payload)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """登录

    分流规则：
    - 账号在本地 users 表且 auth_source='local' → 本地密码校验
    - 其余情况 → 走 OA 校验（OA 未配置时直接报「该账号不存在」）
    """
    result = await db.execute(select(User).where(User.loginid == body.loginid))
    user = result.scalar_one_or_none()

    # —— 分支 1：本地账号（local）——
    if user is not None and (user.auth_source or "local") == "local":
        if not verify_password(body.password, user.salt, user.password_hash):
            logger.warning(f"登录失败：密码错误 {body.loginid}")
            await record_action(
                actor={"loginid": user.loginid, "is_admin": user.is_admin,
                       "姓名": user.name or user.loginid},
                action="auth.login", target_type="auth", target_id=user.loginid,
                request=request, result="fail",
                detail={"reason": "密码错误"},
            )
            return LoginResponse(success=False, message="账号或密码错误")

        user_info = UserInfo(
            loginid=user.loginid,
            姓名=user.name or user.loginid,
            部门=user.department or "",
            岗位=user.job_title or ("管理员" if user.is_admin else "用户"),
            is_admin=user.is_admin,
            must_change_password=bool(user.must_change_password),
            auth_source=user.auth_source or "local",
        )

        token = _issue_token(user)
        user.updated_at = get_current_time()
        await db.commit()

        await record_action(
            actor=user_info.model_dump(),
            action="auth.login", target_type="auth", target_id=user.loginid,
            request=request,
            detail={"is_admin": user.is_admin, "auth_source": "local"},
        )

        logger.info(f"登录成功（本地账号）：{user.loginid}")
        return LoginResponse(success=True, message="登录成功", token=token, user_info=user_info)

    # —— 分支 2：OA 账号 ——
    if not oa_enabled():
        logger.warning(f"登录失败：账号不存在且未配置 OA {body.loginid}")
        await record_action(
            actor={"loginid": body.loginid, "is_admin": False, "姓名": body.loginid},
            action="auth.login", target_type="auth", target_id=body.loginid,
            request=request, result="fail",
            detail={"reason": "账号不存在"},
        )
        return LoginResponse(success=False, message="账号或密码错误")

    success, oa_info, message = await oa_login_with_password(body.loginid, body.password)
    if not success or not oa_info:
        logger.warning(f"登录失败（OA）：{body.loginid} -> {message}")
        await record_action(
            actor={"loginid": body.loginid, "is_admin": False, "姓名": body.loginid},
            action="auth.login", target_type="auth", target_id=body.loginid,
            request=request, result="fail",
            detail={"reason": "OA 校验失败", "oa_message": message[:200]},
        )
        return LoginResponse(success=False, message=message)

    # OA 首次登录 → 本地建档（不存密码，is_admin 一律 False，由管理员在库里手动提升）
    if user is None:
        user = User(
            loginid=body.loginid,
            password_hash="",
            salt="",
            name=oa_info.get("姓名") or body.loginid,
            department=oa_info.get("部门") or "",
            job_title=oa_info.get("岗位") or "",
            auth_source="oa",
            is_admin=False,
            must_change_password=False,
        )
        db.add(user)
        logger.info(f"OA 用户首次登录，已在本地建档：{user.loginid}")
    else:
        # 已存在（可能是管理员手动提升过权限）→ 只同步 OA 侧信息，不动 is_admin
        user.name = oa_info.get("姓名") or user.name
        user.department = oa_info.get("部门") or user.department
        user.job_title = oa_info.get("岗位") or user.job_title
        user.auth_source = "oa"
    await db.commit()
    await db.refresh(user)

    user_info = UserInfo(
        loginid=user.loginid,
        姓名=user.name or user.loginid,
        部门=user.department or "",
        岗位=user.job_title or "用户",
        is_admin=bool(user.is_admin),
        must_change_password=False,
        auth_source="oa",
    )

    token = _issue_token(user)
    user.updated_at = get_current_time()
    await db.commit()

    await record_action(
        actor=user_info.model_dump(),
        action="auth.login", target_type="auth", target_id=user.loginid,
        request=request,
        detail={"is_admin": user.is_admin, "auth_source": "oa"},
    )

    logger.info(f"登录成功（OA）：{user.loginid}")
    return LoginResponse(success=True, message="登录成功", token=token, user_info=user_info)


@router.post("/logout")
async def logout(
    request: Request,
    user_info: dict = Depends(get_current_user),
):
    """登出（前端清 localStorage 即可，后端无状态）"""
    await record_action(
        actor=user_info, action="auth.logout",
        target_type="auth", target_id=user_info.get("loginid"),
        request=request,
    )
    return {"success": True, "message": "已登出"}


@router.get("/me")
async def get_me(user_info: dict = Depends(get_current_user)):
    """返回当前登录用户信息"""
    return {"success": True, "user_info": user_info}


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_info: dict = Depends(get_current_user_required),
):
    """改密：需提供旧密码（仅本地账号；OA 账号密码由 OA 侧维护）"""
    loginid = user_info.get("loginid")
    if not loginid:
        raise HTTPException(status_code=401, detail="未登录")

    result = await db.execute(select(User).where(User.loginid == loginid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    if (user.auth_source or "local") == "oa":
        await record_action(
            actor=user_info, action="auth.change_password",
            target_type="auth", target_id=loginid,
            request=request, result="fail",
            detail={"reason": "OA 账号不支持本地改密"},
        )
        return ChangePasswordResponse(
            success=False, message="OA 账号请在 OA 系统修改密码"
        )

    if not body.new_password or len(body.new_password) < 6:
        await record_action(
            actor=user_info, action="auth.change_password",
            target_type="auth", target_id=loginid,
            request=request, result="fail",
            detail={"reason": "新密码长度不足 6 位"},
        )
        return ChangePasswordResponse(success=False, message="新密码长度至少 6 位")

    if not verify_password(body.old_password, user.salt, user.password_hash):
        await record_action(
            actor=user_info, action="auth.change_password",
            target_type="auth", target_id=loginid,
            request=request, result="fail",
            detail={"reason": "旧密码错误"},
        )
        return ChangePasswordResponse(success=False, message="旧密码错误")

    forced = bool(user.must_change_password)
    salt_hex, hash_hex = hash_password(body.new_password)
    user.salt = salt_hex
    user.password_hash = hash_hex
    user.must_change_password = False  # 强制改密完成
    await db.commit()

    await record_action(
        actor=user_info, action="auth.change_password",
        target_type="auth", target_id=loginid,
        request=request,
        detail={"forced": forced},
    )

    logger.info(f"改密成功：{loginid}")
    return ChangePasswordResponse(success=True, message="密码已修改")