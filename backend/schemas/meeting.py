"""
会议相关的 Pydantic Schemas
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from backend.core.filename_utils import sanitize_filename


# ---------- Init Upload ----------

class MeetingInitUploadRequest(BaseModel):
    """初始化上传请求（前端先调用此接口拿到 meeting_id，再上传文件）
    注：MD5 改由后端读取文件时实算，不再由前端声明（防止伪造 / 篡改）
    """
    file_name: str = Field(..., description="原始文件名", max_length=255)
    file_size: int = Field(..., ge=0, description="文件大小(字节)")
    file_type: Optional[str] = Field(None, description="文件扩展名")

    @field_validator("file_name")
    @classmethod
    def _clean_file_name(cls, v: str) -> str:
        # 过滤路径分隔符 / 控制字符 / 引号，防 header 注入与存储脏数据
        return sanitize_filename(v, max_len=255)


class MeetingInitUploadResponse(BaseModel):
    """初始化上传响应"""
    meeting_id: int
    duplicate: bool = Field(False, description="是否命中已存在的 MD5")
    upload_url: Optional[str] = Field(None, description="如果 duplicate 则给出已存在记录的 URL")


# ---------- Meeting ----------

class MeetingBase(BaseModel):
    file_name: str
    file_size: int = 0
    file_type: Optional[str] = None
    duration: Optional[float] = None
    status: Optional[str] = None
    speaker_cnt: int = 0
    meeting_time: Optional[str] = None
    meeting_topic: Optional[str] = None
    meeting_agenda: Optional[str] = None
    meeting_address: Optional[str] = None
    speaker_names: Optional[List[str]] = None
    speaker_titles: Optional[List[str]] = None
    template_key: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MeetingResponse(MeetingBase):
    id: int
    transcript_markdown: Optional[str] = None
    meeting_minutes: Optional[str] = None

    class Config:
        from_attributes = True


class MeetingListResponse(BaseModel):
    items: List[MeetingResponse]
    total: int
    page: int
    page_size: int


# ---------- Meeting Minutes ----------

class MeetingMinutesRequest(BaseModel):
    """生成会议纪要请求"""
    meeting_time: str = Field(..., description="会议时间")
    meeting_topic: str = Field(..., description="会议主题")
    meeting_agenda: Optional[str] = Field(None, description="会议议题")
    meeting_address: Optional[str] = Field(None, description="会议地址")
    speaker_names: List[str] = Field(default_factory=list, description="参会人员姓名")
    speaker_titles: List[str] = Field(default_factory=list, description="参会人员职称")
    template_key: str = Field(..., description="模板 key")


class MeetingMinutesResponse(BaseModel):
    meeting_id: int
    meeting_minutes: str


# ---------- Transcript ----------

class TranscriptSegmentItem(BaseModel):
    speaker: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    text: Optional[str] = None


class MeetingTranscriptResponse(BaseModel):
    meeting_id: int
    transcript_markdown: Optional[str] = None
    segments: List[TranscriptSegmentItem] = Field(default_factory=list)
    speaker_cnt: int = 0


# ---------- Settings ----------

class LLMConfigRequest(BaseModel):
    # 注意：默认必须是 None。update_llm_config 用「is not None」判断是否写入，
    # 若这里给了具体默认值，客户端不传的字段也会被默认值覆盖写库
    # （会把用户配的 max_tokens 打回 16384、enable_thinking 打回 False）。
    api_key: Optional[str] = None
    model: Optional[str] = None
    api_endpoint: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_thinking: Optional[bool] = None


class LLMConfigResponse(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    api_endpoint: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 16384
    enable_thinking: bool = False


class ASRConfigRequest(BaseModel):
    api_url: Optional[str] = None
    api_key: Optional[str] = None


class ASRConfigResponse(BaseModel):
    api_url: Optional[str] = None
    api_key: Optional[str] = None


class TemplatesResponse(BaseModel):
    templates: dict


# ---------- 通用 ----------

class GenericResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None