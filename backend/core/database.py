"""
数据库连接和会话管理
"""
import urllib.parse
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from .config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ensure_database_exists():
    """检查目标数据库是否存在，不存在则自动创建"""
    encoded_password = urllib.parse.quote_plus(settings.DB_PASSWORD)
    server_url = (
        f"mysql+aiomysql://{settings.DB_USER}:{encoded_password}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/"
    )
    server_engine = create_async_engine(server_url, echo=False, poolclass=NullPool)
    try:
        async with server_engine.begin() as conn:
            result = await conn.execute(
                text("SHOW DATABASES LIKE :db_name"),
                {"db_name": settings.DB_NAME},
            )
            if not result.fetchone():
                logger.info(f"目标数据库 {settings.DB_NAME} 不存在，正在自动创建...")
                await conn.execute(text(
                    f"CREATE DATABASE `{settings.DB_NAME}` "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                ))
                logger.info(f"目标数据库 {settings.DB_NAME} 创建成功")
            else:
                logger.info(f"目标数据库 {settings.DB_NAME} 已存在")
    finally:
        await server_engine.dispose()


async def init_db():
    """初始化数据库结构（自动建表）+ seed 默认管理员"""
    await ensure_database_exists()

    # 必须先 import 所有 model，Base.metadata 才能 create_all 出全部表
    from backend.models import system_settings, meeting, user, audit_log, task_queue  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 兼容老库：Base.metadata.create_all 不会 ALTER 已存在的 users 表加列
    # 用 MySQL 8.0 原生支持的 IF NOT EXISTS 做幂等 schema 升级
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "must_change_password TINYINT(1) NOT NULL DEFAULT 0"
            ))
        except Exception:
            pass

    # 兼容老库：meetings 的长文本列从 TEXT(65535 字节) 升级为 LONGTEXT
    await _upgrade_meeting_text_columns()

    # 兼容老库：OA 登录引入的 users 表新列
    await _upgrade_user_oa_columns()

    # seed 默认管理员
    await _seed_default_admin()


# OA 登录引入的 users 表新列：{列名: 完整列定义}
_USER_OA_COLUMNS = {
    "auth_source": "VARCHAR(20) NOT NULL DEFAULT 'local' COMMENT '账号来源：local/oa'",
    "job_title": "VARCHAR(64) NULL COMMENT '岗位'",
}


async def _upgrade_user_oa_columns():
    """给已存在的 users 表补上 OA 登录需要的新列（幂等）"""
    try:
        async with engine.begin() as conn:
            existing = {
                r[0] for r in (
                    await conn.execute(text(
                        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'"
                    ))
                ).all()
            }
            for column, ddl in _USER_OA_COLUMNS.items():
                if column in existing:
                    continue
                await conn.execute(text(f"ALTER TABLE `users` ADD COLUMN `{column}` {ddl}"))
                logger.info(f"users.{column} 已添加")
            # OA 账号不存本地密码，放宽 NOT NULL 约束以便存空串
            await conn.execute(text(
                "ALTER TABLE `users` MODIFY COLUMN `password_hash` VARCHAR(255) NOT NULL DEFAULT ''"
            ))
            await conn.execute(text(
                "ALTER TABLE `users` MODIFY COLUMN `salt` VARCHAR(64) NOT NULL DEFAULT ''"
            ))
    except Exception as e:
        # 升级失败不阻断启动（OA 登录会不可用，但本地账号仍可用）
        logger.warning(f"升级 users 表 OA 相关列失败: {e}")


# 需要升级为 LONGTEXT 的列：{列名: 完整列定义}
# 注意 MODIFY COLUMN 不写全属性会重置 NULL/NOT NULL 与列注释，这里写全。
_LONGTEXT_COLUMNS = {
    "transcript_markdown": "LONGTEXT NULL COMMENT '转写 Markdown 全文'",
    "meeting_minutes": "LONGTEXT NULL COMMENT '会议纪要（LLM 生成）'",
}


async def _upgrade_meeting_text_columns():
    """把 meetings 的长文本列升级为 LONGTEXT（幂等，可重复执行）

    MySQL 的 TEXT 上限 65,535 字节，长会议转写会报 DataError(1406)。
    先查 information_schema 判断当前类型，只在需要时 ALTER 一次，
    避免每次启动都触发一次表重建。
    """
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'meetings' "
                "AND COLUMN_NAME IN ('transcript_markdown', 'meeting_minutes')"
            ))).all()
            for column_name, data_type in rows:
                if (data_type or "").lower() == "longtext":
                    continue  # 已是 LONGTEXT，跳过
                ddl = _LONGTEXT_COLUMNS.get(column_name)
                if not ddl:
                    continue
                await conn.execute(text(
                    f"ALTER TABLE `meetings` MODIFY COLUMN `{column_name}` {ddl}"
                ))
                logger.info(f"meetings.{column_name} 已由 TEXT 升级为 LONGTEXT")
    except Exception as e:
        # 升级失败不阻断启动（只是长文本仍受 TEXT 64KB 限制）
        logger.warning(f"升级 meetings 长文本列为 LONGTEXT 失败: {e}")


async def _seed_default_admin():
    """默认管理员账号的初始化与同步

    管理员的登录信息以 .env（DEFAULT_ADMIN_USER / DEFAULT_ADMIN_PASSWORD / DEFAULT_ADMIN_NAME）
    为唯一来源，每次启动都会对齐：

    1. users 表为空 → 创建管理员（首次登录强制改密）
    2. 管理员账号已存在 → 密码与 .env 不一致时，按 .env 重置密码
       （运维改 .env 后重启即生效；界面上改的密码会在下次重启被 .env 覆盖 —— 这是
        「凭据统一由部署配置管理」的刻意设计）
       is_admin 不动，避免覆盖运维手动做的降权操作
    """
    from backend.core.config import settings
    from backend.core.security import hash_password, verify_password
    from backend.models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        existing = result.scalar_one_or_none()

        if existing is None:
            # —— 首次启动：建管理员 ——
            salt_hex, hash_hex = hash_password(settings.DEFAULT_ADMIN_PASSWORD)
            admin = User(
                loginid=settings.DEFAULT_ADMIN_USER,
                password_hash=hash_hex,
                salt=salt_hex,
                name=settings.DEFAULT_ADMIN_NAME,
                department="系统管理",
                job_title="管理员",
                auth_source="local",
                is_admin=True,
                must_change_password=True,  # seed 出来的账号必须先改密才能进系统
            )
            session.add(admin)
            await session.commit()
            logger.info(
                f"已创建默认管理员账号: {settings.DEFAULT_ADMIN_USER}（首次登录会被强制改密）"
            )
            return

        # —— 已有账号：对齐 .env 里的管理员凭据 ——
        admin = (await session.execute(
            select(User).where(User.loginid == settings.DEFAULT_ADMIN_USER)
        )).scalar_one_or_none()
        if admin is None:
            logger.info(
                f"users 表非空但不存在管理员账号 {settings.DEFAULT_ADMIN_USER}，跳过同步"
            )
            return

        if (admin.auth_source or "local") != "local":
            logger.warning(
                f"账号 {settings.DEFAULT_ADMIN_USER} 的 auth_source="
                f"{admin.auth_source}，不是本地账号，跳过密码同步"
            )
            return

        # 用 verify 判断「库里的密码是否已经等于 .env 里的密码」
        if admin.salt and verify_password(
            settings.DEFAULT_ADMIN_PASSWORD, admin.salt, admin.password_hash
        ):
            # 密码一致，只同步展示名
            if admin.name != settings.DEFAULT_ADMIN_NAME:
                admin.name = settings.DEFAULT_ADMIN_NAME
                await session.commit()
                logger.info(f"管理员 {admin.loginid} 的显示名已同步为 {settings.DEFAULT_ADMIN_NAME}")
            return

        # 密码不一致 → 按 .env 重置
        salt_hex, hash_hex = hash_password(settings.DEFAULT_ADMIN_PASSWORD)
        admin.salt = salt_hex
        admin.password_hash = hash_hex
        admin.name = settings.DEFAULT_ADMIN_NAME
        await session.commit()
        logger.warning(
            f"管理员账号 {admin.loginid} 的密码与 .env 中 DEFAULT_ADMIN_PASSWORD 不一致，"
            f"已按 .env 重置（若此前在界面上改过密码，此处会被覆盖）"
        )