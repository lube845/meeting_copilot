"""
会议纪要模板服务 - 从 JSON 文件加载/写入模板
"""
import json
import logging
from pathlib import Path

from backend.core.config import settings

logger = logging.getLogger(__name__)


# 内联默认模板（当配置文件缺失时使用）
DEFAULT_TEMPLATES = {
    "标准会议纪要": (
        "# 会议纪要\n\n"
        "## 会议概览\n"
        "- 时间: {{会议时间}}\n"
        "- 主题: {{会议主题}}\n"
        "- 地址: {{会议地址}}\n"
        "- 参会人员: {{参会人员}}\n\n"
        "## 关键结论\n- \n\n"
        "## 行动项\n"
        "- 负责人: \n"
        "- 截止时间: \n\n"
        "## 讨论要点\n- "
    ),
    "简洁版": (
        "# 会议纪要\n\n"
        "- 时间: {{会议时间}}\n"
        "- 主题: {{会议主题}}\n"
        "- 地址: {{会议地址}}\n\n"
        "## 结论\n- \n\n"
        "## 待办\n- "
    ),
    "决策跟踪": (
        "# 决策跟踪会议纪要\n\n"
        "## 会议信息\n"
        "- 时间: {{会议时间}}\n"
        "- 主题: {{会议主题}}\n"
        "- 议题: {{会议议题}}\n"
        "- 地址: {{会议地址}}\n"
        "- 参会人员: {{参会人员}}\n\n"
        "## 已达成决策\n"
        "1. \n\n"
        "## 待跟进事项\n"
        "| 事项 | 负责人 | 截止时间 | 状态 |\n"
        "| --- | --- | --- | --- |\n"
        "|  |  |  | 待开始 |\n\n"
        "## 风险与阻塞\n- \n\n"
        "## 下次会议\n- 时间: \n- 议题: "
    ),
}


def _resolve_path() -> Path:
    """解析模板文件路径：绝对路径直接用；相对路径先在 cwd 找，再到项目根找"""
    template_path = Path(settings.MEETING_TEMPLATES_PATH)
    if template_path.is_absolute():
        return template_path
    if template_path.exists():
        return template_path
    return Path(__file__).resolve().parents[2] / template_path.name


def load_templates() -> dict:
    """从配置文件加载会议纪要模板（失败则回退到内联默认）"""
    try:
        full_path = _resolve_path()
        if full_path.exists():
            with open(full_path, "r", encoding="utf-8") as f:
                templates = json.load(f)
                if isinstance(templates, dict) and templates:
                    logger.info(f"已加载会议纪要模板: {full_path} ({len(templates)} 个)")
                    return templates
    except Exception as e:
        logger.warning(f"加载模板失败: {e}, 使用默认模板")

    return DEFAULT_TEMPLATES


def get_template_keys() -> list[str]:
    """获取所有模板名称（用于前端 selectbox 选项）"""
    return list(load_templates().keys())


def save_templates(templates: dict) -> bool:
    """把模板字典写回配置文件（按 JSON 格式，可读性好）"""
    try:
        full_path = _resolve_path()
        # 确保父目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存模板到 {full_path} ({len(templates)} 个)")
        return True
    except Exception as e:
        logger.error(f"保存模板失败: {e}")
        raise


def upsert_template(key: str, content: str) -> dict:
    """新增或更新一个模板；返回最新的模板字典"""
    templates = load_templates()
    if not key or not key.strip():
        raise ValueError("模板名称不能为空")
    templates[key] = content
    save_templates(templates)
    return templates


def delete_template(key: str) -> dict:
    """删除一个模板；返回最新的模板字典"""
    templates = load_templates()
    if key not in templates:
        raise KeyError(f"模板 '{key}' 不存在")
    del templates[key]
    save_templates(templates)
    return templates