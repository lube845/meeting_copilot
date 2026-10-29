"""
后台任务队列服务

设计：
- DB 表 (task_queues) + asyncio 守护协程 (worker_loop)
- lifespan 启动时 spawn 一个 worker，每秒扫一次 PENDING/RETRY 且 next_run_at<=now 的行
- 用 SELECT ... FOR UPDATE SKIP LOCKED（MySQL 8.0+）原子认领，避免多 worker 抢同一任务
- 执行过程分阶段更新 progress / progress_text，前端轮询可见
- 失败按 attempts/max_attempts 决定 retry（指数退避）或 failed

执行步骤：
1. enqueue(...) 创建任务行，状态 PENDING
2. worker_loop 每秒 claim_next_pending() 一条
3. 根据 task.type 调 _run_transcribe / _run_minutes
4. 业务代码调 update_progress() 更新进度
5. 完成后 mark_success()，失败调 mark_retry_or_failed()
"""
from __future__ import annotations

import asyncio
import os
import socket
from datetime import timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import AsyncSessionLocal
from backend.core.datetime_utils import get_current_time
from backend.models.meeting import Meeting, MeetingStatus, TranscriptSegment
from backend.models.task_queue import TaskQueue, TaskStatus, TaskType
from backend.services.asr_service import asr_service
from backend.services.meeting_service import generate_minutes
from backend.services.oss_service import oss_service
from backend.services.template_service import load_templates
from backend.services.audit_service import record_action


# ——— worker 实例标识 ———
def _make_instance_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


_INSTANCE_ID = _make_instance_id()

# ——— 生命周期信号（lifespan 控制 worker 退出）——
_shutdown_event: Optional[asyncio.Event] = None
_worker_task: Optional[asyncio.Task] = None


def install_shutdown_event(event: asyncio.Event) -> None:
    """由 lifespan 调用，注册关闭信号"""
    global _shutdown_event
    _shutdown_event = event


# ——— 重试退避 ———
def _backoff_seconds(attempts: int) -> int:
    """指数退避：第 N 次失败后等 N^2 秒（上限 5 分钟）"""
    return min(60 * (2 ** max(attempts - 1, 0)), 300)


# ——— 任务创建（API 层调用）——

async def enqueue(
    db: AsyncSession,
    *,
    type: TaskType,
    meeting_id: int,
    max_attempts: int = 3,
) -> TaskQueue:
    """创建一条 PENDING 任务，立即返回。worker_loop 会自动认领"""
    task = TaskQueue(
        type=type,
        meeting_id=meeting_id,
        status=TaskStatus.PENDING,
        attempts=0,
        max_attempts=max_attempts,
        progress=0,
        progress_text="等待执行",
        next_run_at=get_current_time(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    logger.info(f"task_queue enqueue: id={task.id} type={type.value} meeting_id={meeting_id}")
    return task


async def get_latest_for_meeting(db: AsyncSession, meeting_id: int) -> TaskQueue | None:
    """获取某会议最新一条任务（用于前端轮询）"""
    row = await db.execute(
        select(TaskQueue)
        .where(TaskQueue.meeting_id == meeting_id)
        .order_by(TaskQueue.id.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


# ——— worker 主循环 ———

async def worker_loop() -> None:
    """lifespan 启动的常驻协程：每秒扫一次、认领一条任务执行

    退出条件：_shutdown_event 被 set（lifespan 退出时设置）"""
    global _worker_task
    _worker_task = asyncio.current_task()
    logger.info(f"task_queue_worker started: instance={_INSTANCE_ID}")

    assert _shutdown_event is not None, "worker_loop 启动前必须 install_shutdown_event"

    while not _shutdown_event.is_set():
        try:
            claimed = await _try_claim_one()
            if claimed:
                await _dispatch(claimed)
            else:
                # 没有任务可执行，等 1 秒
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.info("task_queue_worker cancelled")
            break
        except Exception as e:
            logger.error(f"task_queue_worker_loop 异常: {e}", exc_info=True)
            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    logger.info("task_queue_worker stopped")


async def _try_claim_one() -> TaskQueue | None:
    """原子认领一条 pending 任务（用独立 session，不挂在请求上）"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = await session.execute(
                select(TaskQueue)
                .where(
                    TaskQueue.status.in_([TaskStatus.PENDING, TaskStatus.RETRY]),
                    TaskQueue.next_run_at <= get_current_time(),
                )
                .order_by(TaskQueue.id.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            task = row.scalar_one_or_none()
            if task is None:
                return None
            task.status = TaskStatus.RUNNING
            task.attempts += 1
            task.locked_by = _INSTANCE_ID
            task.locked_at = get_current_time()
            task.progress_text = "已认领，准备执行"
            return task


async def _dispatch(task: TaskQueue) -> None:
    """根据 type 分派到对应执行函数"""
    logger.info(f"task_queue_worker claimed: id={task.id} type={task.type.value} "
                f"meeting_id={task.meeting_id} attempts={task.attempts}")
    try:
        if task.type == TaskType.TRANSCRIBE:
            await _run_transcribe(task.id)
        elif task.type == TaskType.GENERATE_MINUTES:
            await _run_minutes(task.id)
        else:
            logger.error(f"未知任务类型: {task.type}")
            await _mark_failed_by_id(task.id, f"未知任务类型: {task.type}")
    except Exception as e:
        logger.error(f"_dispatch 顶层异常: {e}", exc_info=True)


# ——— 进度/状态辅助（独立 session，避免污染业务事务）——

async def update_progress(task_id: int, progress: int, text: str) -> None:
    """更新进度（前端轮询可见）"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            task = await session.get(TaskQueue, task_id)
            if task is None:
                return
            task.progress = progress
            task.progress_text = text


async def mark_success(task_id: int) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            task = await session.get(TaskQueue, task_id)
            if task is None:
                return
            task.status = TaskStatus.SUCCESS
            task.progress = 100
            task.progress_text = "完成"
            task.error_message = None
            task.locked_by = None
            task.locked_at = None
    logger.info(f"task_queue_worker task_id={task_id} success")


async def _mark_failed_by_id(task_id: int, error: str) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            task = await session.get(TaskQueue, task_id)
            if task is None:
                return
            task.status = TaskStatus.FAILED
            task.error_message = error
            task.progress_text = "失败"
            task.locked_by = None
            task.locked_at = None
    logger.error(f"task_queue_worker task_id={task_id} failed: {error}")


async def mark_retry_or_failed(
    task_id: int,
    meeting_id: int,
    error: str,
) -> None:
    """失败后：未超 max_attempts → RETRY + 指数退避；否则 FAILED + 改 meeting.status=FAILED"""
    final_failed = False
    async with AsyncSessionLocal() as session:
        async with session.begin():
            task = await session.get(TaskQueue, task_id)
            if task is None:
                return
            if task.attempts < task.max_attempts:
                task.status = TaskStatus.RETRY
                task.next_run_at = get_current_time() + timedelta(
                    seconds=_backoff_seconds(task.attempts)
                )
                task.progress_text = f"失败，{_backoff_seconds(task.attempts)}s 后重试"
                task.error_message = error
                task.locked_by = None
                task.locked_at = None
                logger.warning(
                    f"task_queue_worker task_id={task_id} retry: "
                    f"attempts={task.attempts}/{task.max_attempts} err={error}"
                )
            else:
                task.status = TaskStatus.FAILED
                task.progress_text = "失败（已重试耗尽）"
                task.error_message = error
                task.locked_by = None
                task.locked_at = None
                logger.error(
                    f"task_queue_worker task_id={task_id} failed (exhausted): {error}"
                )
                # 把会议也置为 FAILED
                m = await session.get(Meeting, meeting_id)
                if m:
                    m.status = MeetingStatus.FAILED
                    m.error_message = error
                final_failed = True

    # 事务外写审计（避免嵌套连接冲突 + 5 分钟去重被同一事务覆盖）
    if final_failed:
        async with AsyncSessionLocal() as session:
            task = await session.get(TaskQueue, task_id)
            if task is None:
                return
            action_name = (
                "meeting.transcribe_fail"
                if task.type == TaskType.TRANSCRIBE
                else "meeting.minutes_fail"
            )
            try:
                await record_action(
                    actor=None,
                    action=action_name,
                    target_type="meeting",
                    target_id=str(meeting_id),
                    result="fail",
                    detail={"task_id": task_id, "error": error[:500]},
                )
            except Exception as e:
                logger.warning(f"audit 写入失败: {e}")


# ——— 转写任务 ———

async def _run_transcribe(task_id: int) -> None:
    """执行 ASR 转写：下载 → ASR → 写回。分阶段更新进度。"""
    # 先取出 meeting_id（不挂在 task session 里，避免后续 session 切换）
    async with AsyncSessionLocal() as session:
        task = await session.get(TaskQueue, task_id)
        if task is None:
            return
        meeting_id = task.meeting_id

    try:
        await update_progress(task_id, 5, "加载会议信息")
        async with AsyncSessionLocal() as session:
            m = await session.get(
                Meeting, meeting_id, options=[selectinload(Meeting.segments)]
            )
            if m is None:
                await _mark_failed_by_id(task_id, "会议不存在")
                return
            if not m.oss_object_key:
                await _mark_failed_by_id(task_id, "OSS 对象键缺失")
                return
            m.status = MeetingStatus.TRANSCRIBING
            await session.commit()

        await update_progress(task_id, 30, "下载音频")
        async with AsyncSessionLocal() as session:
            m = await session.get(Meeting, meeting_id)
            object_key = m.oss_object_key if m else None
        if not object_key:
            await _mark_failed_by_id(task_id, "会议对象键已丢失")
            return
        file_bytes = await oss_service.get_file(object_key)

        await update_progress(task_id, 50, "ASR 转写中（可能数分钟）")
        async with AsyncSessionLocal() as session:
            m = await session.get(Meeting, meeting_id)
            file_name = m.file_name if m else "audio"
        result = await asr_service.transcribe_bytes(file_name, file_bytes)

        await update_progress(task_id, 95, "写入数据库")
        async with AsyncSessionLocal() as session:
            m = await session.get(
                Meeting, meeting_id, options=[selectinload(Meeting.segments)]
            )
            if m is None:
                await _mark_failed_by_id(task_id, "会议在写入前被删除")
                return
            m.transcript_markdown = result["markdown"]
            m.speaker_cnt = result["speaker_cnt"]
            m.status = MeetingStatus.TRANSCRIBED
            for seg in m.segments:
                await session.delete(seg)
            await session.flush()
            for item in result["segments"]:
                session.add(TranscriptSegment(
                    meeting_id=m.id,
                    speaker=str(item.get("speaker")),
                    start_time=item.get("start"),
                    end_time=item.get("end"),
                    text=item.get("text"),
                ))
            await session.commit()

        await mark_success(task_id)
        logger.info(f"会议 {meeting_id} 转写完成: speaker_cnt={result.get('speaker_cnt')}")
    except Exception as e:
        logger.error(f"会议 {meeting_id} 转写失败: {e}", exc_info=True)
        await mark_retry_or_failed(task_id, meeting_id, str(e))


# ——— 纪要生成任务 ———

async def _run_minutes(task_id: int) -> None:
    """执行 LLM 纪要生成：读转写 + 元数据 → 模板填充 → LLM → 写回"""
    async with AsyncSessionLocal() as session:
        task = await session.get(TaskQueue, task_id)
        if task is None:
            return
        meeting_id = task.meeting_id

    try:
        await update_progress(task_id, 10, "加载会议与转写")
        async with AsyncSessionLocal() as session:
            m = await session.get(Meeting, meeting_id)
            if m is None:
                await _mark_failed_by_id(task_id, "会议不存在")
                return
            if not m.transcript_markdown:
                await _mark_failed_by_id(task_id, "转写尚未完成")
                return
            meeting_time = m.meeting_time or ""
            meeting_topic = m.meeting_topic or ""
            meeting_agenda = m.meeting_agenda or ""
            meeting_address = m.meeting_address or ""
            speaker_names = m.speaker_names or []
            speaker_titles = m.speaker_titles or []
            speaker_cnt = m.speaker_cnt or 0
            template_key = m.template_key or "标准会议纪要"
            transcript = m.transcript_markdown

        # 模板
        templates = load_templates()
        template_content = (
            templates.get(template_key) or templates.get("标准会议纪要") or ""
        )
        if not template_content:
            await _mark_failed_by_id(task_id, f"模板不存在: {template_key}")
            return

        # 替换说话人
        transcript_processed = _replace_speaker_names(
            transcript, speaker_names, speaker_titles
        )
        speaker_map = _build_speaker_map(speaker_names, speaker_titles, speaker_cnt)
        participants = _format_participants(speaker_names, speaker_titles)

        await update_progress(task_id, 40, "调用 LLM 生成纪要")
        minutes = await generate_minutes(
            meeting_time=meeting_time,
            meeting_topic=meeting_topic,
            meeting_agenda=meeting_agenda,
            meeting_address=meeting_address,
            participants=participants,
            speaker_map=speaker_map,
            template=template_content,
            transcript=transcript_processed,
        )

        await update_progress(task_id, 95, "写入数据库")
        async with AsyncSessionLocal() as session:
            m = await session.get(Meeting, meeting_id)
            if m is None:
                await _mark_failed_by_id(task_id, "会议在写入前被删除")
                return
            m.meeting_minutes = minutes
            if m.status == MeetingStatus.TRANSCRIBED:
                m.status = MeetingStatus.READY
            await session.commit()

        await mark_success(task_id)
        logger.info(f"会议 {meeting_id} 纪要生成完成: length={len(minutes)}")
    except Exception as e:
        logger.error(f"会议 {meeting_id} 纪要生成失败: {e}", exc_info=True)
        await mark_retry_or_failed(task_id, meeting_id, str(e))


# ——— 内部辅助（和原 api/meeting.py 重复的 helper，复制过来避免循环依赖）——

import re  # noqa: E402


def _replace_speaker_names(content: str, speaker_names: list, speaker_titles: list) -> str:
    """说话人0/1/... → 真实姓名(职称)。用数字边界防说话人10 被说话人1 误伤"""
    for i, name in enumerate(speaker_names):
        name = (name or "").strip()
        title = (
            speaker_titles[i].strip()
            if i < len(speaker_titles) and speaker_titles[i]
            else ""
        )
        if name or title:
            full = name if not title else f"{name}({title})"
            content = re.sub(rf"说话人{i}(?!\d)", full, content)
    return content


def _build_speaker_map(speaker_names: list, speaker_titles: list, cnt: int) -> str:
    """说话人0 -> 张三(CEO)"""
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
    """'张三(CEO)、李四(CTO)'"""
    parts = []
    for i, name in enumerate(speaker_names):
        name = (name or "").strip()
        title = (
            speaker_titles[i].strip()
            if i < len(speaker_titles) and speaker_titles[i]
            else ""
        )
        if name or title:
            full = name if not title else f"{name}({title})"
            parts.append(full)
    return "、".join(parts) if parts else "未填写"
