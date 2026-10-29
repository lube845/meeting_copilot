"""
ASR 客户端服务 - 通过 HTTP 调用独立的 ASR 服务（FunASR 单独部署）

注意：本服务不加载模型，仅作为 backend → asr_server 之间的薄客户端。
ASR 服务进程见项目根目录的 asr_server.py 与 docker/Dockerfile.asr。
"""
import httpx
from loguru import logger

from backend.services.config_service import config_service


class AsrService:
    """ASR HTTP 客户端"""

    def __init__(self, timeout: float = 1800):
        self.timeout = timeout  # 默认 30 分钟（大文件长音视频小）
        self._api_url: str | None = None

    async def _resolve_api_url(self) -> str:
        """读取 ASR 服务 URL：优先数据库配置（前端「系统设置」在线修改），其次 .env 默认值

        与 LLM 侧保持一致：config_service 内部就是「数据库优先、env 兜底」，
        .env 里的 ASR_API_URL 只作为部署期的默认值。
        """
        if self._api_url:
            return self._api_url
        cfg = await config_service.get_asr_config()
        self._api_url = (cfg.get("api_url") or "").rstrip("/")
        return self._api_url

    async def refresh_config(self):
        self._api_url = None

    async def health(self) -> dict:
        """健康检查：调用 ASR 服务的 /health"""
        api_url = await self._resolve_api_url()
        if not api_url:
            return {"status": "not_configured", "model_loaded": False, "supported_formats": []}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{api_url}/health")
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning(f"ASR 健康检查失败: {e}")
            return {"status": "unreachable", "model_loaded": False, "error": str(e)}

    async def transcribe_bytes(self, filename: str, content: bytes) -> dict:
        """上传音频字节到 ASR 服务，返回 (markdown, segments, speaker_cnt)

        Raises:
            RuntimeError: ASR 服务未配置或调用失败
        """
        api_url = await self._resolve_api_url()
        if not api_url:
            raise RuntimeError("ASR_API_URL 未配置；请检查 .env 或 /settings/asr")

        content_type = self._guess_content_type(filename)
        files = {"upload_file": (filename or "audio.wav", content, content_type)}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{api_url}/transcribe_upload/",
                    files=files,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            raise RuntimeError(f"ASR 转写超时（{self.timeout}s）")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"ASR 服务返回 HTTP {e.response.status_code}: {e.response.text[:300]}")
        except Exception as e:
            raise RuntimeError(f"ASR 调用失败: {e}")

        if data.get("status") != "success":
            raise RuntimeError(f"ASR 返回错误: {data.get('detail', data)}")

        return {
            "markdown": data.get("markdown", ""),
            "segments": data.get("segments", []),
            "speaker_cnt": data.get("speaker_cnt", 0),
        }

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        ext = (filename or "").rsplit(".", 1)[-1].lower()
        return {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "mp4": "audio/mp4",
            "m4a": "audio/mp4",
            "flac": "audio/flac",
            "ogg": "audio/ogg",
            "webm": "audio/webm",
            "amr": "audio/amr",
        }.get(ext, "application/octet-stream")


# 单例
asr_service = AsrService()