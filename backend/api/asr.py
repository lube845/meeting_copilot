"""
ASR 路由 - 通过 HTTP 调用独立 ASR 服务（需登录）
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends

from backend.services.asr_service import asr_service
from backend.api.auth import get_current_user

router = APIRouter(prefix="/asr", tags=["asr"], dependencies=[Depends(get_current_user)])


@router.get("/health")
async def health():
    """健康检查接口（代理 ASR 服务）"""
    return await asr_service.health()


@router.post("/transcribe-upload")
async def transcribe_upload(upload_file: UploadFile = File(...)):
    """上传音频文件，返回 Markdown 转写 + segments + 说话人数量（代理 ASR 服务）"""
    if not upload_file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")

    try:
        content = await upload_file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")

        result = await asr_service.transcribe_bytes(upload_file.filename, content)
        return {
            "status": "success",
            "speaker_cnt": result["speaker_cnt"],
            "markdown": result["markdown"],
            "segments": result["segments"],
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        # ASR 客户端抛出的错误（未配置/超时/HTTP 错误）
        raise HTTPException(status_code=502, detail=f"ASR 服务调用失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"转写失败: {e}")