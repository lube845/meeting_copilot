"""
会议路由 - 上传、列表、详情、删除、纪要生成（异步）、播放、导出、任务进度查询
"""
import hashlib
import io
import logging
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.core.filename_utils import build_content_disposition, sanitize_filename
from backend.models.meeting import Meeting, MeetingStatus, TranscriptSegment
from backend.models.task_queue import TaskType
from backend.schemas.meeting import (
    MeetingInitUploadRequest,
    MeetingInitUploadResponse,
    MeetingListResponse,
    MeetingMinutesRequest,
    MeetingResponse,
    MeetingTranscriptResponse,
    TranscriptSegmentItem,
)
from backend.services import task_queue_service
from backend.services.audit_service import record_action
from backend.services.oss_service import oss_service
from backend.services.template_service import load_templates, get_template_keys
from backend.api.auth import get_current_user

router = APIRouter(prefix="/meetings", tags=["meetings"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)


def _meeting_to_response(m: Meeting) -> MeetingResponse:
    """ORM → Response（处理 JSON 字段 fallback）"""
    return MeetingResponse(
        id=m.id,
        file_name=m.file_name,
        file_size=m.file_size or 0,
        file_type=m.file_type,
        duration=m.duration,
        status=m.status.value if m.status else None,
        speaker_cnt=m.speaker_cnt or 0,
        meeting_time=m.meeting_time,
        meeting_topic=m.meeting_topic,
        meeting_agenda=m.meeting_agenda,
        meeting_address=m.meeting_address,
        speaker_names=m.speaker_names or [],
        speaker_titles=m.speaker_titles or [],
        template_key=m.template_key,
        error_message=m.error_message,
        created_at=m.created_at,
        updated_at=m.updated_at,
        transcript_markdown=m.transcript_markdown,
        meeting_minutes=m.meeting_minutes,
    )


def _speaker_map(speaker_names: list, speaker_titles: list, cnt: int) -> str:
    """构建说话人映射字符串（用于模型参考：说话人N -> 真实身份）"""
    lines = []
    for i in range(cnt):
        name = (speaker_names[i] if i < len(speaker_names) else "") or ""
        title = (speaker_titles[i] if i < len(speaker_titles) else "") or ""
        name = name.strip()
        title = title.strip()
        if name or title:
            full = name if not title else f"{name}({title})"
            lines.append(f"说话人{i} -> {full}")
        else:
            lines.append(f"说话人{i} -> 说话人{i}")
    return "\n".join(lines)


def _format_participants(speaker_names: list, speaker_titles: list) -> str:
    """格式化为「参会人员」展示串：'张三(CEO)、李四(CTO)'"""
    parts = []
    for i, name in enumerate(speaker_names):
        name = (name or "").strip()
        title = (speaker_titles[i] if i < len(speaker_titles) else "").strip() if i < len(speaker_titles) else ""
        if name or title:
            full = name if not title else f"{name}({title})"
            parts.append(full)
    return "、".join(parts) if parts else "未填写"


def _replace_speaker_names(content: str, speaker_names: list, speaker_titles: list) -> str:
    """把 说话人0/1/... 替换为真实姓名（带数字边界，避免说话人10 被说话人1 误伤）"""
    for i, name in enumerate(speaker_names):
        name = (name or "").strip()
        title = (speaker_titles[i] if i < len(speaker_titles) else "").strip() if i < len(speaker_titles) else ""
        if name or title:
            full = name if not title else f"{name}({title})"
            content = re.sub(rf"说话人{i}(?!\d)", full, content)
    return content


# ---------- 路由 ----------

@router.post("/init-upload", response_model=MeetingInitUploadResponse)
async def init_upload(
    body: MeetingInitUploadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_info: dict = Depends(get_current_user),
):
    """初始化上传：创建 Meeting 记录（MD5 等文件读完后由服务端计算）"""
    m = Meeting(
        file_name=body.file_name,
        file_size=body.file_size,
        file_type=body.file_type,
        status=MeetingStatus.UPLOADING,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    await record_action(
        actor=user_info, action="meeting.init_upload",
        target_type="meeting", target_id=str(m.id),
        target_label=body.file_name,
        request=request,
        detail={"file_size": body.file_size, "file_type": body.file_type},
    )
    return MeetingInitUploadResponse(meeting_id=m.id, duplicate=False)


# 上传大小上限：与 nginx client_max_body_size 对齐
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB
STREAM_CHUNK_BYTES = 4 * 1024 * 1024   # 4MB


@router.post("/{meeting_id}/upload")
async def upload_file(
    meeting_id: int,
    upload_file: UploadFile = File(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user_info: dict = Depends(get_current_user),
):
    """上传音频文件到 MinIO（流式 + 边读边算 MD5），并入队转写任务

    关键变化：
    - 流式分块读取，避免 await read() 整文件进内存（OOM 防护）
    - MD5 在服务端增量计算，避免前端自报
    - 文件写完后做 MD5 去重：若已存在同 MD5 的会议 → 复用旧记录，删除新上传的对象
    - 完成后入队 task_queue（worker_loop 自动认领执行），不再用 BackgroundTasks
    """
    m = await db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")

    object_key = oss_service.generate_object_key(upload_file.filename or m.file_name)
    md5 = hashlib.md5()
    total = 0

    try:
        buf = bytearray()
        while True:
            chunk = await upload_file.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            buf.extend(chunk)
            md5.update(chunk)
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大（>{MAX_UPLOAD_BYTES // (1024*1024)} MB），已拒绝",
                )
        if total == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")

        digest = md5.hexdigest()

        # 去重：若 DB 已存在同 MD5 → 复用、删掉本次上传的对象
        existing = await db.execute(select(Meeting).where(Meeting.file_md5 == digest))
        existing_meeting = existing.scalar_one_or_none()
        if existing_meeting and existing_meeting.id != meeting_id:
            # 把当前 meeting 标记为 duplicate，删掉空记录；前端会拿到 duplicate=true
            await db.delete(m)
            await db.commit()
            await record_action(
                actor=user_info, action="meeting.upload",
                target_type="meeting", target_id=str(existing_meeting.id),
                target_label=existing_meeting.file_name,
                request=request, result="success",
                detail={"duplicate": True, "file_md5": digest},
            )
            return {
                "meeting_id": existing_meeting.id,
                "status": "duplicate",
                "object_key": existing_meeting.oss_object_key,
            }

        await oss_service.upload_file(
            bytes(buf), object_key, content_type=upload_file.content_type or "audio/mpeg"
        )

        m.oss_object_key = object_key
        m.oss_bucket = oss_service.bucket
        m.file_size = total
        m.file_md5 = digest
        m.status = MeetingStatus.UPLOADED
        await db.commit()

        # 入队转写任务（持久化，进程崩溃后可恢复）
        await task_queue_service.enqueue(
            db, type=TaskType.TRANSCRIBE, meeting_id=meeting_id,
        )

        await record_action(
            actor=user_info, action="meeting.upload",
            target_type="meeting", target_id=str(meeting_id),
            target_label=m.file_name,
            request=request,
            detail={"file_size": total, "file_md5": digest},
        )

        return {"meeting_id": meeting_id, "status": "uploaded", "object_key": object_key}
    except HTTPException:
        raise
    except Exception as e:
        try:
            m.status = MeetingStatus.FAILED
            m.error_message = f"上传失败: {e}"
            await db.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.get("", response_model=MeetingListResponse)
async def list_meetings(
    page: int = 1,
    page_size: Optional[int] = None,
    keyword: Optional[str] = None,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """分页获取会议列表"""
    from backend.core.config import settings

    page = max(1, page)
    page_size = page_size or settings.DEFAULT_PAGE_SIZE
    page_size = min(page_size, settings.MAX_PAGE_SIZE)

    stmt = select(Meeting)
    count_stmt = select(func.count(Meeting.id))

    if keyword:
        like = f"%{keyword}%"
        cond = or_(
            Meeting.file_name.like(like),
            Meeting.meeting_topic.like(like),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if status_filter:
        try:
            stmt = stmt.where(Meeting.status == MeetingStatus(status_filter))
            count_stmt = count_stmt.where(Meeting.status == MeetingStatus(status_filter))
        except ValueError:
            pass

    # 日期范围（按 created_at 过滤，前端传 'YYYY-MM-DD'）
    if date_from:
        try:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d")
            stmt = stmt.where(Meeting.created_at >= start_dt)
            count_stmt = count_stmt.where(Meeting.created_at >= start_dt)
        except ValueError:
            pass
    if date_to:
        try:
            # 包含整个 date_to 日
            end_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            stmt = stmt.where(Meeting.created_at <= end_dt)
            count_stmt = count_stmt.where(Meeting.created_at <= end_dt)
        except ValueError:
            pass

    stmt = stmt.order_by(Meeting.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    total = (await db.execute(count_stmt)).scalar() or 0
    items = (await db.execute(stmt)).scalars().all()

    return MeetingListResponse(
        items=[_meeting_to_response(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(meeting_id: int, db: AsyncSession = Depends(get_db)):
    m = await db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")
    return _meeting_to_response(m)


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: int,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user_info: dict = Depends(get_current_user),
):
    m = await db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")

    file_name = m.file_name
    oss_key = m.oss_object_key

    # 删除 OSS 对象
    if oss_key:
        try:
            await oss_service.delete_file(oss_key)
        except Exception as e:
            logger.warning(f"删除 OSS 对象失败: {e}")

    await db.delete(m)
    await db.commit()

    await record_action(
        actor=user_info, action="meeting.delete",
        target_type="meeting", target_id=str(meeting_id),
        target_label=file_name,
        request=request,
    )
    return {"success": True}


@router.post("/{meeting_id}/minutes")
async def generate_meeting_minutes(
    meeting_id: int,
    body: MeetingMinutesRequest,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user_info: dict = Depends(get_current_user),
):
    """生成会议纪要：异步任务

    立即把元数据存库 + 入队 LLM 任务，返回 task_id。前端通过 GET /{meeting_id}/task 轮询进度。
    """
    m = await db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")
    if not m.transcript_markdown:
        raise HTTPException(status_code=400, detail="转写尚未完成，无法生成纪要")

    # 元数据先存（即使纪要还没生成），让 worker 能拿到
    m.meeting_time = body.meeting_time
    m.meeting_topic = body.meeting_topic
    m.meeting_agenda = body.meeting_agenda
    m.meeting_address = body.meeting_address
    m.speaker_names = body.speaker_names
    m.speaker_titles = body.speaker_titles
    m.template_key = body.template_key
    await db.commit()

    # 入队纪要生成任务
    task = await task_queue_service.enqueue(
        db, type=TaskType.GENERATE_MINUTES, meeting_id=meeting_id,
    )

    await record_action(
        actor=user_info, action="meeting.generate_minutes",
        target_type="meeting", target_id=str(meeting_id),
        target_label=m.file_name,
        request=request,
        detail={"template_key": body.template_key, "task_id": task.id},
    )

    return {
        "meeting_id": meeting_id,
        "task_id": task.id,
        "status": "pending",
        "message": "会议纪要生成任务已入队，请通过 /meetings/{id}/task 轮询进度",
    }


@router.get("/{meeting_id}/task")
async def get_latest_task(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取会议最新一条任务的进度（前端轮询用，2s 一次）"""
    task = await task_queue_service.get_latest_for_meeting(db, meeting_id)
    if not task:
        return {"status": "none"}
    return {
        "task_id": task.id,
        "type": task.type.value,
        "status": task.status.value,
        "progress": task.progress,
        "progress_text": task.progress_text,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.get("/{meeting_id}/play")
async def get_play_url(meeting_id: int, db: AsyncSession = Depends(get_db)):
    """获取 MinIO presigned 播放 URL"""
    m = await db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")
    if not m.oss_object_key:
        raise HTTPException(status_code=400, detail="音频尚未上传")
    signed = await oss_service.get_presigned_url(m.oss_object_key, expires=3600)
    return {"play_url": signed, "expires_in": 3600}


@router.get("/{meeting_id}/export-docx")
async def export_docx(meeting_id: int, db: AsyncSession = Depends(get_db)):
    """导出包含会议纪要 + 转写全文的 Word 文档（pypandoc）"""
    m = await db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")
    if not m.meeting_minutes:
        raise HTTPException(status_code=400, detail="尚未生成会议纪要，无法导出")

    # 处理转写（替换说话人）
    speaker_names = m.speaker_names or []
    speaker_titles = m.speaker_titles or []
    processed_transcript = _replace_speaker_names(m.transcript_markdown or "", speaker_names, speaker_titles)

    # 参会人员
    participants = []
    for i, name in enumerate(speaker_names):
        name = (name or "").strip()
        title = (speaker_titles[i] if i < len(speaker_titles) else "").strip() if i < len(speaker_titles) else ""
        if name or title:
            full = name if not title else f"{name}({title})"
            participants.append(full)
    participants_str = ", ".join(participants) if participants else "未填写"

    md_content = (
        f"# 会议纪要\n\n"
        f"## 会议信息\n\n"
        f"**会议时间**: {m.meeting_time or '未填写'}\n\n"
        f"**会议主题**: {m.meeting_topic or '未填写'}\n\n"
        f"**参会人员**: {participants_str}\n\n"
        f"**会议议题**: {m.meeting_agenda or '未填写'}\n\n"
        f"**会议地址**: {m.meeting_address or '未填写'}\n\n"
        f"---\n\n"
        f"{m.meeting_minutes}\n\n"
        f"---\n\n"
        f"## 附录：转写全文\n\n"
        f"{processed_transcript}\n"
    )

    try:
        docx_bytes = _pandoc_md_to_bytes(md_content)
    except Exception as e:
        logger.error(f"pandoc 转换失败: {e}")
        raise HTTPException(status_code=500, detail=f"Word 导出失败: {e}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = sanitize_filename(m.file_name, max_len=120, default="meeting")
    base = base.rsplit(".", 1)[0] if "." in base else base
    filename = f"会议纪要_{base}_{ts}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": build_content_disposition(
                filename, fallback=f"meeting_minutes_{ts}.docx"
            )
        },
    )


def _pandoc_md_to_bytes(md_text: str) -> bytes:
    """通过 pypandoc 把 Markdown 转为 docx 字节流"""
    from pypandoc import convert_file

    md_path = None
    target_path = None
    try:
        with NamedTemporaryFile(suffix=".md", delete=False) as md_file:
            md_file.write(md_text.encode("utf-8"))
            md_file.flush()
            md_path = md_file.name
        with NamedTemporaryFile(suffix=".docx", delete=False) as target:
            target_path = target.name
        convert_file(
            source_file=md_path,
            format="markdown",
            to="docx",
            outputfile=target_path,
            extra_args=["--standalone"],
        )
        return Path(target_path).read_bytes()
    finally:
        if md_path and Path(md_path).exists():
            Path(md_path).unlink()
        if target_path and Path(target_path).exists():
            Path(target_path).unlink()