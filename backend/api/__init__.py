"""
API路由汇总
"""
from .auth import router as auth_router
from .asr import router as asr_router
from .meeting import router as meeting_router
from .transcript import router as transcript_router
from .settings import router as settings_router

__all__ = [
    "auth_router",
    "asr_router",
    "meeting_router",
    "transcript_router",
    "settings_router",
]