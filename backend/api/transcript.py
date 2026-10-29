"""
转写路由 - 返回 Markdown 与分段（需登录）
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.models.meeting import Meeting
from backend.schemas.meeting import MeetingTranscriptResponse, TranscriptSegmentItem
from backend.api.auth import get_current_user

router = APIRouter(prefix="/meetings", tags=["transcript"], dependencies=[Depends(get_current_user)])


@router.get("/{meeting_id}/transcript", response_model=MeetingTranscriptResponse)
async def get_transcript(meeting_id: int, db: AsyncSession = Depends(get_db)):
    m = await db.get(Meeting, meeting_id, options=[selectinload(Meeting.segments)])
    if not m:
        raise HTTPException(status_code=404, detail="会议不存在")

    segments = [
        TranscriptSegmentItem(
            speaker=seg.speaker,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=seg.text,
        )
        for seg in m.segments
    ]

    return MeetingTranscriptResponse(
        meeting_id=meeting_id,
        transcript_markdown=m.transcript_markdown,
        segments=segments,
        speaker_cnt=m.speaker_cnt or 0,
    )