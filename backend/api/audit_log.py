"""
审计日志查询 API（移植自 VoxAudit）

- GET  列表：分页 + 筛选（admin）
- GET  actions / actors：枚举下拉选项（admin）
- GET  export：导出 CSV（admin）
- POST record：前端埋点写入入口（任意已登录用户）
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, func, or_

from backend.core.database import get_db
from backend.core.filename_utils import build_content_disposition
from backend.models.audit_log import AuditLog
from backend.api.auth import require_admin, get_current_user_required
from backend.services.audit_service import record_action


router = APIRouter(tags=["审计日志"])


# ——— 入参 ———
class RecordRequest(BaseModel):
    """前端埋点写入入口"""
    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail: dict[str, Any] | None = None


# ——— 序列化 ———
def _serialize(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "actor_loginid": row.actor_loginid,
        "actor_name": row.actor_name,
        "actor_role": row.actor_role,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "target_label": row.target_label,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "result": row.result,
        "detail": row.detail,
    }


# ——— 接口 ———
@router.get("/admin/audit-logs", dependencies=[Depends(require_admin)])
async def list_audit_logs(
    actor_loginid: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    keyword: str | None = None,
    start_time: str | None = None,  # ISO
    end_time: str | None = None,
    include_page_view: bool = Query(False, description="是否包含 page.view 类，默认 false"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    """审计日志列表（admin）"""
    db = await get_db().__anext__()

    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))

    # 默认隐藏 page.view 类噪音（页面访问量大且价值低）
    if not include_page_view:
        stmt = stmt.where(AuditLog.action != "page.view")
        count_stmt = count_stmt.where(AuditLog.action != "page.view")

    if actor_loginid:
        stmt = stmt.where(AuditLog.actor_loginid == actor_loginid)
        count_stmt = count_stmt.where(AuditLog.actor_loginid == actor_loginid)

    if action:
        # 支持前缀匹配（meeting. 匹配所有 meeting.*）
        like_pat = f"{action}%"
        stmt = stmt.where(AuditLog.action.like(like_pat))
        count_stmt = count_stmt.where(AuditLog.action.like(like_pat))

    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
        count_stmt = count_stmt.where(AuditLog.target_type == target_type)

    if keyword:
        like_kw = f"%{keyword}%"
        kw_cond = or_(
            AuditLog.target_label.like(like_kw),
            AuditLog.actor_loginid.like(like_kw),
            AuditLog.actor_name.like(like_kw),
        )
        stmt = stmt.where(kw_cond)
        count_stmt = count_stmt.where(kw_cond)

    if start_time:
        try:
            dt = datetime.fromisoformat(start_time)
            stmt = stmt.where(AuditLog.created_at >= dt)
            count_stmt = count_stmt.where(AuditLog.created_at >= dt)
        except ValueError:
            pass

    if end_time:
        try:
            dt = datetime.fromisoformat(end_time)
            stmt = stmt.where(AuditLog.created_at <= dt)
            count_stmt = count_stmt.where(AuditLog.created_at <= dt)
        except ValueError:
            pass

    total = (await db.execute(count_stmt)).scalar() or 0

    offset = (page - 1) * page_size
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    items = [_serialize(r) for r in rows]

    await db.close()
    return {"success": True, "items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/admin/audit-logs/actions", dependencies=[Depends(require_admin)])
async def list_actions():
    """枚举所有出现过的 action（admin，下拉用）"""
    db = await get_db().__anext__()
    stmt = (
        select(AuditLog.action, func.count(AuditLog.id).label("cnt"))
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    await db.close()
    items = [{"action": r[0], "count": r[1]} for r in rows]
    return {"success": True, "items": items}


@router.get("/admin/audit-logs/actors", dependencies=[Depends(require_admin)])
async def list_actors():
    """枚举所有出现过的操作人（admin，下拉用）"""
    db = await get_db().__anext__()
    stmt = (
        select(
            AuditLog.actor_loginid,
            AuditLog.actor_name,
            AuditLog.actor_role,
            func.count(AuditLog.id).label("cnt"),
        )
        .group_by(AuditLog.actor_loginid, AuditLog.actor_name, AuditLog.actor_role)
        .order_by(func.count(AuditLog.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    await db.close()
    items = [
        {"loginid": r[0], "name": r[1], "role": r[2], "count": r[3]}
        for r in rows
    ]
    return {"success": True, "items": items}


@router.get("/admin/audit-logs/export", dependencies=[Depends(require_admin)])
async def export_logs(
    actor_loginid: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    keyword: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    include_page_view: bool = Query(False, description="是否包含 page.view 类，默认 false"),
):
    """导出筛选结果为 CSV（admin）"""
    db = await get_db().__anext__()

    stmt = select(AuditLog)
    if not include_page_view:
        stmt = stmt.where(AuditLog.action != "page.view")
    if actor_loginid:
        stmt = stmt.where(AuditLog.actor_loginid == actor_loginid)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if keyword:
        like_kw = f"%{keyword}%"
        stmt = stmt.where(or_(
            AuditLog.target_label.like(like_kw),
            AuditLog.actor_loginid.like(like_kw),
            AuditLog.actor_name.like(like_kw),
        ))
    if start_time:
        try:
            dt = datetime.fromisoformat(start_time)
            stmt = stmt.where(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if end_time:
        try:
            dt = datetime.fromisoformat(end_time)
            stmt = stmt.where(AuditLog.created_at <= dt)
        except ValueError:
            pass

    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(10000)
    rows = (await db.execute(stmt)).scalars().all()
    await db.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "created_at", "actor_loginid", "actor_name", "actor_role",
        "action", "target_type", "target_id", "target_label",
        "ip", "user_agent", "result", "detail",
    ])
    for r in rows:
        writer.writerow([
            r.id,
            r.created_at.isoformat() if r.created_at else "",
            r.actor_loginid, r.actor_name or "", r.actor_role or "",
            r.action, r.target_type or "", r.target_id or "", r.target_label or "",
            r.ip or "", r.user_agent or "", r.result,
            json.dumps(r.detail, ensure_ascii=False) if r.detail else "",
        ])

    csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM 便于 Excel 打开
    filename = f"audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": build_content_disposition(filename)},
    )


@router.post("/admin/audit-logs/record")
async def record_frontend_action(
    payload: RecordRequest,
    request: Request,
    user_info: dict = Depends(get_current_user_required),
):
    """前端埋点写入入口（任意已登录用户）

    用于 page.view / Tab 切换 / 筛选按钮等纯 UI 操作。
    """
    await record_action(
        actor=user_info,
        action=payload.action,
        target_type=payload.target_type,
        target_id=payload.target_id,
        request=request,
        detail=payload.detail,
    )
    return {"success": True}
