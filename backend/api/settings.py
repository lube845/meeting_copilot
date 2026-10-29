"""
系统设置路由 - LLM/ASR/模板配置 + 测试连接

权限：
- 读接口（GET）  : 登录即可
- 写/测接口      : 仅管理员（require_admin）
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from backend.services.config_service import config_service
from backend.services.template_service import (
    load_templates,
    get_template_keys,
    upsert_template,
    delete_template,
)
from backend.services.meeting_service import test_llm_connection, test_asr_connection
from backend.services.llm_service import llm_service
from backend.services.asr_service import asr_service
from backend.core.config import settings
from backend.core.url_safety import assert_safe_http_url, UnsafeURLError
from backend.schemas.meeting import (
    LLMConfigRequest,
    LLMConfigResponse,
    ASRConfigRequest,
    ASRConfigResponse,
    TemplatesResponse,
)
from backend.api.auth import get_current_user, require_admin

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])


def _assert_service_url(url: str, label: str) -> None:
    """统一的 LLM/ASR 地址校验（SSRF 防护）

    按 ALLOW_INTERNAL_SERVICE_URLS 决定是否允许指向内网地址：
    - True（默认）：允许回环与 RFC1918 / fc00::/7（ASR、LLM 常与后端同机同网段）
    - False：完全禁止内网地址
    链路本地（169.254/16，云元数据）、非 http(s) 协议永远拒绝。
    """
    try:
        assert_safe_http_url(url, allow_private=settings.ALLOW_INTERNAL_SERVICE_URLS)
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=f"{label} 不合法: {e}")


class TemplateUpsertRequest(BaseModel):
    """新增/更新一个模板"""
    key: str
    content: str


@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config():
    """获取 LLM 配置（敏感字段脱敏：api_key 用 ***）"""
    cfg = await config_service.get_llm_config()
    return LLMConfigResponse(
        api_key="***" if cfg.get("api_key") else "",
        model=cfg.get("model", ""),
        api_endpoint=cfg.get("api_endpoint", ""),
        temperature=cfg.get("temperature", 0.1),
        max_tokens=cfg.get("max_tokens", 16384),
        enable_thinking=cfg.get("enable_thinking", False),
    )


@router.put("/llm", response_model=LLMConfigResponse, dependencies=[Depends(require_admin)])
async def update_llm_config(body: LLMConfigRequest):
    """更新 LLM 配置到数据库（仅管理员）"""
    updates = []
    if body.api_key is not None and body.api_key != "***":
        updates.append(("LLM_API_KEY", body.api_key, True))
    if body.model is not None:
        updates.append(("LLM_MODEL", body.model, False))
    if body.api_endpoint is not None:
        # SSRF 防护：写入前先校验目标 URL（LLM 侧此前缺失，ASR 侧有）
        _assert_service_url(body.api_endpoint, "LLM API URL")
        updates.append(("LLM_API_ENDPOINT", body.api_endpoint, False))
    if body.temperature is not None:
        updates.append(("LLM_TEMPERATURE", str(body.temperature), False))
    if body.max_tokens is not None:
        updates.append(("LLM_MAX_TOKENS", str(body.max_tokens), False))
    if body.enable_thinking is not None:
        updates.append(("LLM_ENABLE_THINKING", "true" if body.enable_thinking else "false", False))

    for key, value, is_secret in updates:
        await config_service.upsert_setting(key, value, is_secret=is_secret)

    # 立即刷新缓存（LLM + ASR，避免后续请求拿到旧值）
    await llm_service.refresh_config()
    await asr_service.refresh_config()
    return await get_llm_config()


@router.post("/llm/test", dependencies=[Depends(require_admin)])
async def test_llm(body: LLMConfigRequest):
    """测试 LLM 配置是否可用（仅管理员）"""
    # 优先使用 body 中的值（用户尚未保存也想测），回退到数据库
    cfg = await config_service.get_llm_config()
    api_endpoint = body.api_endpoint or cfg.get("api_endpoint", "")
    api_key = body.api_key if body.api_key and body.api_key != "***" else cfg.get("api_key", "")
    model = body.model or cfg.get("model", "")
    temperature = body.temperature if body.temperature is not None else cfg.get("temperature", 0.1)

    if not api_endpoint:
        raise HTTPException(status_code=400, detail="LLM API URL 未配置")
    if not model:
        raise HTTPException(status_code=400, detail="LLM 模型未配置")
    # SSRF 防护：测试接口同样会让服务端发起请求，必须校验
    _assert_service_url(api_endpoint, "LLM API URL")

    result = await test_llm_connection(
        api_endpoint=api_endpoint,
        api_key=api_key,
        model=model,
        temperature=temperature,
    )
    return result


@router.get("/asr", response_model=ASRConfigResponse)
async def get_asr_config():
    """获取 ASR 配置（脱敏）"""
    cfg = await config_service.get_asr_config()
    return ASRConfigResponse(
        api_url=cfg.get("api_url", ""),
        api_key="***" if cfg.get("api_key") else "",
    )


@router.put("/asr", response_model=ASRConfigResponse, dependencies=[Depends(require_admin)])
async def update_asr_config(body: ASRConfigRequest):
    """更新 ASR 配置（仅管理员）"""
    if body.api_url is not None:
        # SSRF 防护：写入前先校验目标 URL
        _assert_service_url(body.api_url, "ASR API URL")
        await config_service.upsert_setting("ASR_API_URL", body.api_url)
    if body.api_key is not None and body.api_key != "***":
        await config_service.upsert_setting("ASR_API_KEY", body.api_key, is_secret=True)
    # 立即让 asr_service 重新加载（否则下一次转写仍打到旧 URL）
    await asr_service.refresh_config()
    return await get_asr_config()


@router.post("/asr/test", dependencies=[Depends(require_admin)])
async def test_asr(body: ASRConfigRequest):
    """测试 ASR 服务连通性（仅管理员）"""
    cfg = await config_service.get_asr_config()
    api_url = body.api_url or cfg.get("api_url", "")
    if not api_url:
        raise HTTPException(status_code=400, detail="ASR API URL 未配置")
    _assert_service_url(api_url, "ASR API URL")
    return await test_asr_connection(api_url)


@router.get("/templates", response_model=TemplatesResponse)
async def get_templates():
    """获取会议纪要模板列表"""
    return TemplatesResponse(templates=load_templates())


@router.put("/templates", response_model=TemplatesResponse, dependencies=[Depends(require_admin)])
async def upsert_template_endpoint(body: TemplateUpsertRequest):
    """新增或更新一个模板（按 key 唯一，仅管理员）"""
    try:
        templates = upsert_template(body.key, body.content)
        return TemplatesResponse(templates=templates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存模板失败: {e}")


@router.delete("/templates/{key}", response_model=TemplatesResponse, dependencies=[Depends(require_admin)])
async def delete_template_endpoint(key: str):
    """删除一个模板（仅管理员）"""
    try:
        templates = delete_template(key)
        return TemplatesResponse(templates=templates)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除模板失败: {e}")