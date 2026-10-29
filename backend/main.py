"""
智能会议助手 - 主入口
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from backend.core.config import settings
from backend.core.database import init_db
from backend.services.oss_service import oss_service
from backend.services import task_queue_service
from backend.middleware.audit_middleware import audit_middleware
from backend.api import asr_router, meeting_router, transcript_router, settings_router
from backend.api.audit_log import router as audit_log_router
from backend.api.auth import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 让 TZ 环境变量对 datetime.now() 真正生效（Unix only）
    tz = os.environ.get("TZ")
    if tz:
        try:
            time.tzset()
            logger.info(f"TZ={tz} 已生效")
        except Exception as e:
            logger.warning(f"time.tzset() 不可用，TZ={tz} 未生效: {e}")

    logger.info(f"正在启动 {settings.APP_NAME}...")
    try:
        await init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")

    try:
        await oss_service.init_buckets()
        logger.info("MinIO存储桶初始化完成")
    except Exception as e:
        logger.warning(f"MinIO存储桶初始化失败（桶可能已存在）: {e}")

    # 启动 task_queue 后台 worker
    shutdown_event = asyncio.Event()
    task_queue_service.install_shutdown_event(shutdown_event)
    worker_task = asyncio.create_task(task_queue_service.worker_loop())

    try:
        yield
    finally:
        logger.info("正在关闭应用...")
        shutdown_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("task_queue_worker 已停止")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="上传会议录音 → 智能转写 → 生成会议纪要 → 导出 Word",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    # 慢请求阈值：> 5s 打 WARNING，> 30s 打 ERROR
    if process_time > 30:
        logger.error(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s (SLOW)")
    elif process_time > 5:
        logger.warning(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s (slow)")
    else:
        logger.info(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s")
    return response


# 审计中间件（自动埋点）
app.middleware("http")(audit_middleware)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"全局异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误", "message": str(exc)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """把 Pydantic 验证错误转成中文友好提示"""
    field_names = {
        "meeting_time": "会议时间",
        "meeting_topic": "会议主题",
        "meeting_agenda": "会议议题",
        "meeting_address": "会议地址",
        "speaker_names": "参会人员姓名",
        "speaker_titles": "参会人员职称",
        "template_key": "模板",
        "file_md5": "文件 MD5",
        "file_name": "文件名",
    }
    errors = []
    for err in exc.errors():
        loc = err.get("loc")
        if loc and len(loc) > 1:
            field_key = str(loc[1])
            field_label = field_names.get(field_key, field_key)
            errors.append(f"{field_label}：{err.get('msg', '验证失败')}")
        else:
            errors.append(err.get("msg", '验证失败'))

    message = "；".join(errors) if errors else "验证失败"
    return JSONResponse(
        status_code=422,
        content={"detail": message},
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


# 注册路由
app.include_router(auth_router, prefix="/api/v1")
app.include_router(asr_router, prefix="/api/v1")
app.include_router(meeting_router, prefix="/api/v1")
app.include_router(transcript_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(audit_log_router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
    )
