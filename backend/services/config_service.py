"""
配置服务 - 从数据库读取系统配置
"""
from typing import Optional
from sqlalchemy import select
from backend.core.database import AsyncSessionLocal
from backend.core.config import settings as default_settings
from backend.models.system_settings import SystemSettings


# 默认会议纪要生成 Prompt 模板
# 关键设计：模板里的 {{xxx}} 固定信息已在服务端替换好；
# LLM 的任务 = 在保留已填内容的前提下，把模板里的空白处用转写内容填上。
DEFAULT_PROMPTS = {
    "prompt_meeting_minutes": {
        "system_prompt": (
            "你是一位专业的会议总结工作人员。\n\n"
            "【输入说明】\n"
            "用户已经提前把会议的固定信息（时间、主题、议题、地址、参会人员）填进了一个会议纪要模板里。\n"
            "模板的某些位置留有空白（例如 `- `、`1. `、空标题下方等），等待你根据转写内容补充。\n"
            "你的任务：阅读【会议转写全文】，按【已填好的会议纪要模板】的结构，把空白部分填上合适的内容。\n\n"
            "【输出规则】\n"
            "1. 严格保留模板的标题层级、Markdown 语法、段落顺序，不要改变结构\n"
            "2. 模板中已填好的固定信息（时间、主题、议题、地址、参会人员等）必须原样保留，禁止重写或润色\n"
            "3. 仅在空白处（`-` 后面、空列表项、空白段落）填入从转写中提取的事实\n"
            "4. 客观中立，不要编造转写中没有的结论或行动项\n"
            "5. 输出从模板第一行开始，不要加任何额外说明、前缀或 Markdown 代码块标记"
        ),
        "user_prompt": (
            "【已填好的会议纪要模板】（请严格按此结构输出，空白处填入转写中的内容）\n"
            "```markdown\n"
            "{filled_template}\n"
            "```\n\n"
            "【说话人映射】（说话人N → 真实身份，仅供你理解转写时使用）\n"
            "{speaker_map}\n\n"
            "【会议转写全文】\n"
            "{transcript}\n"
        )
    }
}


class ConfigService:
    """配置服务，从数据库读取配置，如果数据库没有则使用环境变量默认值"""

    @staticmethod
    async def get_setting(key: str) -> Optional[str]:
        """获取单个配置"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SystemSettings).where(SystemSettings.key == key)
            )
            setting = result.scalar_one_or_none()
            return setting.value if setting else None

    @staticmethod
    async def upsert_setting(
        key: str,
        value: Optional[str],
        description: str = "",
        is_secret: bool = False,
        is_system: bool = False,
    ) -> SystemSettings:
        """创建或更新单个配置"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SystemSettings).where(SystemSettings.key == key)
            )
            setting = result.scalar_one_or_none()
            if setting is None:
                setting = SystemSettings(
                    key=key,
                    value=value,
                    description=description,
                    is_secret=is_secret,
                    is_system=is_system,
                )
                session.add(setting)
            else:
                setting.value = value
                if description:
                    setting.description = description
                if is_secret:
                    setting.is_secret = True
            await session.commit()
            await session.refresh(setting)
            return setting

    @staticmethod
    async def get_llm_config() -> dict:
        """获取LLM配置，优先从数据库读取，没有则用默认值"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettings))
            settings_dict = {s.key: s.value for s in result.scalars().all()}

        return {
            "api_key": settings_dict.get("LLM_API_KEY") if settings_dict.get("LLM_API_KEY") is not None else default_settings.LLM_API_KEY,
            "model": settings_dict.get("LLM_MODEL") or default_settings.LLM_MODEL,
            "api_endpoint": settings_dict.get("LLM_API_ENDPOINT") or default_settings.LLM_API_ENDPOINT,
            "temperature": float(settings_dict.get("LLM_TEMPERATURE") or default_settings.LLM_TEMPERATURE),
            "max_tokens": int(settings_dict.get("LLM_MAX_TOKENS") or default_settings.LLM_MAX_TOKENS),
            "enable_thinking": settings_dict.get("LLM_ENABLE_THINKING", "false").lower() == "true",
        }

    @staticmethod
    async def get_asr_config() -> dict:
        """获取ASR配置，优先从数据库读取，没有则用默认值"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettings))
            settings_dict = {s.key: s.value for s in result.scalars().all()}

        return {
            "api_url": settings_dict.get("ASR_API_URL") if settings_dict.get("ASR_API_URL") is not None else default_settings.ASR_API_URL,
            "api_key": settings_dict.get("ASR_API_KEY") if settings_dict.get("ASR_API_KEY") is not None else default_settings.ASR_API_KEY,
        }

    @staticmethod
    async def get_prompt(prompt_key: str) -> dict:
        """获取Prompt模板，优先从数据库读取，没有则用默认值"""
        async with AsyncSessionLocal() as session:
            system_key = prompt_key + "_system"
            user_key = prompt_key + "_user"
            result = await session.execute(
                select(SystemSettings).where(SystemSettings.key.in_([system_key, user_key]))
            )
            settings = {s.key: s.value for s in result.scalars().all()}
            system_value = settings.get(system_key)
            user_value = settings.get(user_key)
            if system_value is not None or user_value is not None:
                return {
                    "system_prompt": system_value or "",
                    "user_prompt": user_value or "",
                }
        default = DEFAULT_PROMPTS.get(prompt_key, {"system_prompt": "你是一个好助手", "user_prompt": "回答用户问题"})
        return default

    @staticmethod
    async def get_all_prompts() -> dict:
        """获取所有Prompt配置"""
        return {
            "prompt_meeting_minutes": await ConfigService.get_prompt("prompt_meeting_minutes"),
        }


config_service = ConfigService()