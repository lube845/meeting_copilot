"""
会议纪要生成服务

设计原则：
- 模板里的 {{xxx}} 占位符在服务端先替换为真实数据
- LLM 拿到的是已填好的模板 + 转写全文
- LLM 的任务是：保留模板中已填的内容，把空白部分根据转写补充完整
"""
import re
from typing import Optional

from loguru import logger

from backend.core.config import settings
from backend.services.llm_service import llm_service
from backend.services.config_service import config_service, DEFAULT_PROMPTS


# 支持的占位符 → 与前端 fields 默认值一致
PLACEHOLDER_KEYS = ["会议时间", "会议主题", "会议议题", "会议地址", "参会人员"]
PLACEHOLDER_RE = re.compile(r"\{\{(" + "|".join(PLACEHOLDER_KEYS) + r")\}\}")


def fill_template_placeholders(template: str, values: dict) -> str:
    """把模板里的 {{key}} 占位符替换为实际值，缺失值用「未填写」"""
    def _replace(m):
        key = m.group(1)
        v = values.get(key, "")
        return v.strip() if v and v.strip() else "未填写"
    return PLACEHOLDER_RE.sub(_replace, template)


async def build_minutes_prompt(
    meeting_time: str,
    meeting_topic: str,
    meeting_agenda: str,
    meeting_address: str,
    speaker_map: str,
    filled_template: str,
    transcript: str,
) -> tuple[str, str]:
    """构造 LLM 调用 prompt（已填好的模板 + 转写全文）

    Returns: (system_message, user_prompt)
    """
    tmpl = await config_service.get_prompt("prompt_meeting_minutes")
    system_message = tmpl["system_prompt"]

    # 已填好的模板作为 user prompt 的核心
    user_prompt = tmpl["user_prompt"].format(
        meeting_time=meeting_time or "未填写",
        meeting_topic=meeting_topic or "未填写",
        meeting_agenda=meeting_agenda or "无",
        meeting_address=meeting_address or "未填写",
        speaker_map=speaker_map or "无",
        filled_template=filled_template,
        transcript=transcript or "无",
    )
    return system_message, user_prompt


async def generate_minutes(
    meeting_time: str,
    meeting_topic: str,
    meeting_agenda: str,
    meeting_address: str,
    participants: str,
    speaker_map: str,
    template: str,
    transcript: str,
    max_tokens: Optional[int] = None,
) -> str:
    """调用 LLM 生成会议纪要（异步）

    关键步骤：
    1. 先把模板里的 {{xxx}} 占位符替换为会议基本信息
    2. 把已填好的模板 + 转写全文作为 prompt 发给 LLM
    3. LLM 只负责把模板中空白处填上转写中提取的内容

    Args:
        meeting_time: 会议时间（用户填写）
        meeting_topic: 会议主题
        meeting_agenda: 会议议题
        meeting_address: 会议地址
        participants: 参会人员展示串（用于填充 {{参会人员}}），如 "张三(CEO)、李四(CTO)"
        speaker_map: 说话人映射（给模型参考），如 "说话人0 -> 张三(CEO)\n说话人1 -> 李四(CTO)"
        template: 模板原文（含 {{xxx}} 占位符）
        transcript: 转写全文
        max_tokens: 最大 token 数；None 表示走系统设置里的 LLM_MAX_TOKENS
    """
    # 1. 服务端预先填好占位符
    filled_template = fill_template_placeholders(
        template,
        {
            "会议时间": meeting_time,
            "会议主题": meeting_topic,
            "会议议题": meeting_agenda,
            "会议地址": meeting_address,
            "参会人员": participants,
        },
    )

    logger.info(
        f"开始生成会议纪要: topic={meeting_topic}, "
        f"模板长度={len(filled_template)}, 转写长度={len(transcript)}"
    )

    # 2. 调用 LLM（关掉 thinking 让输出更聚焦，与 streamlit_app.py:186 行为一致）
    system_message, user_prompt = await build_minutes_prompt(
        meeting_time=meeting_time,
        meeting_topic=meeting_topic,
        meeting_agenda=meeting_agenda,
        meeting_address=meeting_address,
        speaker_map=speaker_map,
        filled_template=filled_template,
        transcript=transcript,
    )

    content = await llm_service.call(
        prompt=user_prompt,
        system_message=system_message,
        max_tokens=max_tokens,
        chat_template_kwargs={"enable_thinking": False},
    )

    logger.info(f"会议纪要生成完成: length={len(content)}")
    return content


async def test_llm_connection(
    api_endpoint: str,
    api_key: str,
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 64,
) -> dict:
    """测试 LLM 连接是否可用"""
    import httpx
    import time

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "你好，请回复'连接成功'四个字。"}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    start = time.time()
    # 连接测试走同步 HTTP，超时封顶 60s（不能超过 nginx proxy_read_timeout）
    probe_timeout = min(int(settings.LLM_TIMEOUT), 60)
    try:
        async with httpx.AsyncClient(timeout=probe_timeout) as client:
            response = await client.post(api_endpoint, headers=headers, json=payload)
            elapsed_ms = int((time.time() - start) * 1000)
            response.raise_for_status()
            result = response.json()

            if result.get("choices"):
                content = result["choices"][0].get("message", {}).get("content", "")
                return {
                    "success": True,
                    "message": "LLM 连接测试成功",
                    "elapsed_ms": elapsed_ms,
                    "reply_preview": content[:200],
                }
            return {
                "success": False,
                "message": f"LLM 返回无 choices 字段: {result}",
                "elapsed_ms": elapsed_ms,
            }
    except httpx.TimeoutException:
        return {"success": False, "message": f"请求超时（{probe_timeout}s）"}
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
        }
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


async def test_asr_connection(api_url: str) -> dict:
    """测试 ASR 服务连通性（默认调用 /health）"""
    import httpx
    import time

    if not api_url:
        return {"success": False, "message": "ASR API URL 未配置"}

    # SSRF 防护：与 settings 接口保持同一策略（调用方也可能漏校验，这里兜底）
    try:
        from backend.core.config import settings
        from backend.core.url_safety import assert_safe_http_url, UnsafeURLError
        assert_safe_http_url(api_url, allow_private=settings.ALLOW_INTERNAL_SERVICE_URLS)
    except UnsafeURLError as e:
        return {"success": False, "message": f"ASR API URL 不合法: {e}"}

    health_url = api_url.rstrip("/") + "/health"

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(health_url)
            elapsed_ms = int((time.time() - start) * 1000)
            response.raise_for_status()
            data = response.json()
            return {
                "success": True,
                "message": "ASR 服务连通",
                "elapsed_ms": elapsed_ms,
                "health": data,
            }
    except httpx.TimeoutException:
        return {"success": False, "message": "请求超时（15s）"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}