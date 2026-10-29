"""
会议数据模型
"""
import enum
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Float, ForeignKey, JSON, Enum
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import relationship

from backend.core.database import Base
from backend.core.datetime_utils import get_current_time


# MySQL 的 TEXT 只有 65,535 字节，长会议转写（约 26,000 中文字符）就写不进去，
# 会报 DataError(1406)。用方言变体在 MySQL 上落成 LONGTEXT，其它方言仍是 TEXT。
MYSQL_LONGTEXT = Text().with_variant(LONGTEXT, "mysql")


class MeetingStatus(enum.Enum):
    """会议处理状态"""
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    UPLOAD_FAILED = "upload_failed"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    TRANSCRIBE_FAILED = "transcribe_failed"
    READY = "ready"
    FAILED = "failed"


class Meeting(Base):
    """会议表"""
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)

    # 文件信息
    file_name = Column(String(255), nullable=False, comment="原始文件名")
    file_size = Column(Integer, default=0, comment="文件大小(字节)")
    file_md5 = Column(String(32), nullable=True, index=True, comment="文件 MD5")
    file_type = Column(String(20), nullable=True, comment="文件类型(mp3/wav/...)")
    duration = Column(Float, nullable=True, comment="录音时长(秒)")

    # 存储信息
    oss_object_key = Column(String(500), nullable=True, comment="OSS 对象键")
    oss_bucket = Column(String(100), nullable=True, comment="OSS Bucket")

    # 状态
    status = Column(
        Enum(MeetingStatus),
        default=MeetingStatus.UPLOADING,
        comment="处理状态",
    )
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 业务字段
    speaker_cnt = Column(Integer, default=0, comment="说话人数量")
    meeting_time = Column(String(100), nullable=True, comment="会议时间(用户填写)")
    meeting_topic = Column(String(255), nullable=True, comment="会议主题")
    meeting_agenda = Column(Text, nullable=True, comment="会议议题")
    meeting_address = Column(String(500), nullable=True, comment="会议地址")
    speaker_names = Column(JSON, nullable=True, comment="参会人员姓名列表")
    speaker_titles = Column(JSON, nullable=True, comment="参会人员职称列表")
    template_key = Column(String(100), nullable=True, comment="使用的模板 key")

    # 转写结果
    transcript_markdown = Column(
        MYSQL_LONGTEXT, nullable=True, comment="转写 Markdown 全文"
    )

    # 纪要结果
    meeting_minutes = Column(
        MYSQL_LONGTEXT, nullable=True, comment="会议纪要（LLM 生成）"
    )

    # 时间戳
    created_at = Column(DateTime, default=get_current_time, comment="创建时间")
    updated_at = Column(
        DateTime, default=get_current_time, onupdate=get_current_time, comment="更新时间"
    )

    segments = relationship(
        "TranscriptSegment",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )


class TranscriptSegment(Base):
    """转写片段表（带时间戳的对话）"""
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False, index=True)
    speaker = Column(String(20), nullable=True, comment="原始说话人 ID，如 speaker_0")
    start_time = Column(Float, nullable=True, comment="开始时间(秒)")
    end_time = Column(Float, nullable=True, comment="结束时间(秒)")
    text = Column(Text, nullable=True, comment="文本内容")

    meeting = relationship("Meeting", back_populates="segments")