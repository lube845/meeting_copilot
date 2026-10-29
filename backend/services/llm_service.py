"""
LLM 调用服务 - 统一封装
"""
import asyncio
import httpx
from loguru import logger
from typing import Optional, Dict, Any

from backend.core.config import settings
from backend.services.config_service import config_service
import re


def strip_think(content: str) -> str:
    """去除大模型输出中的思考过程标签及内容"""
    if not content:
        return content
    cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    return cleaned.strip()


class LLMService:
    """统一的 LLM 调用服务"""

    def __init__(self, timeout: Optional[float] = None):
        # 超时可配置：长会议纪要要吐上万 token，60s 硬编码必然超时
        self.timeout = float(timeout) if timeout is not None else float(settings.LLM_TIMEOUT)
        self._config: Optional[Dict[str, Any]] = None

    async def _ensure_config(self):
        """确保配置已加载"""
        if self._config is None:
            self._config = await config_service.get_llm_config()

    async def refresh_config(self):
        """强制刷新配置（用于配置更新后立即生效）"""
        self._config = await config_service.get_llm_config()

    async def call(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        max_retries: Optional[int] = None,
        chat_template_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        调用 LLM API

        Args:
            prompt: 用户 prompt
            system_message: 系统消息，可选
            max_tokens: 最大 token 数，默认使用系统设置里的 LLM_MAX_TOKENS
            temperature: 温度参数，默认使用配置值
            max_retries: 最大重试次数，默认取 LLM_MAX_RETRIES（2）
            chat_template_kwargs: 透传给 LLM 的额外参数（如 enable_thinking）

        Returns:
            LLM 返回的文本内容
        """
        await self._ensure_config()

        if max_retries is None:
            max_retries = settings.LLM_MAX_RETRIES
        max_retries = max(1, int(max_retries))

        headers = {"Content-Type": "application/json"}
        if self._config.get("api_key"):
            headers["Authorization"] = f"Bearer {self._config['api_key']}"

        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._config["model"],
            "messages": messages,
            "temperature": self._config.get("temperature", 0.1),
            # 不传 max_tokens 时走系统设置（数据库 LLM_MAX_TOKENS 优先、env 兜底）
            "max_tokens": max_tokens or self._config.get("max_tokens") or settings.LLM_MAX_TOKENS,
            "stream": False,
        }

        # 可选：透传 chat_template_kwargs（如 enable_thinking）
        if chat_template_kwargs is not None:
            payload["chat_template_kwargs"] = chat_template_kwargs
        else:
            enable_thinking = self._config.get("enable_thinking", False)
            payload["chat_template_kwargs"] = {
                "enable_thinking": enable_thinking,
                "thinking": enable_thinking,
            }

        endpoint = self._config["api_endpoint"]
        if not endpoint:
            raise Exception("LLM API URL 未配置")

        logger.info(f"调用 LLM API: {endpoint}, Model: {self._config['model']}")

        last_error = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                    response.raise_for_status()
                    result = response.json()

                    if result.get("choices") is None or len(result.get("choices", [])) == 0:
                        error_msg = result.get("base_resp", {}).get("status_msg", "unknown error")
                        raise Exception(f"LLM API 错误: {error_msg}")

                    message = result["choices"][0].get("message", {})
                    content = message.get("content", "")

                    content = strip_think(content)
                    if not content:
                        raise Exception("LLM 返回内容为空")

                    logger.info(f"LLM 返回内容: {content[:200]}...")
                    return content

            except httpx.TimeoutException:
                last_error = Exception(f"LLM 请求超时（{self.timeout}s）")
                logger.warning(f"LLM 超时 (尝试 {attempt + 1}/{max_retries})")
                # 长超时场景下，超时通常意味着服务端还在排队生成，重试只会白等一轮
                # 并重复消耗算力；外层 task_queue 还有重试，这里直接放弃本次调用。
                if self.timeout >= 300:
                    logger.warning("长超时模式：本次超时不再重试，交由 task_queue 任务重试")
                    break
            except httpx.HTTPStatusError as e:
                last_error = Exception(f"LLM HTTP 错误: {e.response.status_code} - {e.response.text}")
                logger.warning(f"LLM HTTP 错误 (尝试 {attempt + 1}/{max_retries}): {last_error}")
            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")

            if attempt < max_retries - 1:
                await asyncio.sleep(2)

        raise last_error

    async def call_json(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        调用 LLM 并返回 JSON 解析后的结果
        """
        import json
        content = await self.call(
            prompt=prompt,
            system_message=system_message,
            max_tokens=max_tokens or 2000,
            temperature=temperature,
            max_retries=max_retries,
        )
        return self._extract_json(content)

    def _extract_json(self, content: str) -> Dict[str, Any]:
        """从文本中提取 JSON"""
        import json
        content = content.strip()
        if not content:
            raise json.JSONDecodeError("内容为空", content, 0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = content[json_start:json_end]
            json_str = json_str.replace(",}", "}")
            json_str = json_str.replace(",]", "]")
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        raise json.JSONDecodeError(f"无法从内容中提取 JSON: {content[:200]}", content, 0)


llm_service = LLMService()