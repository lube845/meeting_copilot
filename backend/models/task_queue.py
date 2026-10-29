"""
任务队列表 - 持久化后台任务

用途：
- ASR 转写（长任务、可能因进程崩溃丢失）
- LLM 纪要生成（长任务）

设计要点：
- DB 表 + asyncio 守护协程（lifespan 启动）实现，避免引入 Celery/ARQ
- SELECT ... FOR UPDATE SKIP LOCKED（MySQL 8.0+）防多 worker 抢同一任务
- 每个任务在执行过程中持续更新 progress / progress_text，前端轮询可看真实进度
- 失败时支持 max_attempts 次重试（间隔指数退避），超限置 FAILED
"""
import enum

from sqlalchemy import (
    Column, BigInteger, Integer, String, DateTime, Text, ForeignKey, Enum,
)

from backend.core.database import Base
from backend.core.datetime_utils import get_current_time


class TaskType(str, enum.Enum):
    """任务类型"""
    TRANSCRIBE = "transcribe"          # ASR 转写
    GENERATE_MINUTES = "minutes"      # LLM 纪要生成


class TaskStatus(str, enum.Enum):
    """任务状态机"""
    PENDING = "pending"     # 等待执行（next_run_at 已到即被 worker 认领）
    RUNNING = "running"     # 正在执行
    SUCCESS = "success"     # 完成
    FAILED = "failed"       # 失败且不再重试（超限）
    RETRY = "retry"         # 临时失败，等 next_run_at 后再试


class TaskQueue(Base):
    """任务队列表"""
    __tablename__ = "task_queues"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="自增ID")

    type = Column(Enum(TaskType), nullable=False, index=True, comment="任务类型")
    meeting_id = Column(
        Integer, ForeignKey("meetings.id"), nullable=False, index=True,
        comment="关联会议 ID",
    )

    # —— 状态 ——
    status = Column(
        Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True,
        comment="任务状态",
    )
    attempts = Column(Integer, default=0, nullable=False, comment="已执行次数")
    max_attempts = Column(Integer, default=3, nullable=False, comment="最大重试次数")

    # —— 进度（前端轮询展示）——
    progress = Column(Integer, default=0, nullable=False, comment="0-100")
    progress_text = Column(String(100), nullable=True, comment="人类可读进度")

    # —— 失败上下文 ——
    error_message = Column(Text, nullable=True, comment="最后一次失败的错误信息")

    # —— 调度 ——
    next_run_at = Column(
        DateTime, default=get_current_time, nullable=False, index=True,
        comment="下次可执行时间（PENDING/RETRY 时使用）",
    )

    # —— 锁（防多 worker 抢同一任务）——
    locked_by = Column(String(64), nullable=True, comment="worker 实例标识")
    locked_at = Column(DateTime, nullable=True, comment="加锁时间")

    # —— 时间戳 ——
    created_at = Column(DateTime, default=get_current_time, nullable=False)
    updated_at = Column(
        DateTime, default=get_current_time, onupdate=get_current_time, nullable=False,
    )
