"""
应用配置模块 - 智能会议助手
"""
import urllib.parse
from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    APP_NAME: str = "智能会议助手"
    APP_VERSION: str = "1.0.0-dev"
    DEBUG: bool = False

    # 数据库配置
    DB_HOST: str = ""
    DB_PORT: int = 3306
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_PASSWORD_ENCRYPTED: str = ""
    DB_SECRET_KEY: str = ""
    DB_NAME: str = ""

    @property
    def DATABASE_URL(self) -> str:
        encoded_password = urllib.parse.quote_plus(self.DB_PASSWORD)
        return f"mysql+aiomysql://{self.DB_USER}:{encoded_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        encoded_password = urllib.parse.quote_plus(self.DB_PASSWORD)
        return f"mysql+pymysql://{self.DB_USER}:{encoded_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # OSS配置
    OSS_ENDPOINT: str = ""
    OSS_ACCESS_KEY: str = ""
    OSS_SECRET_KEY: str = ""
    OSS_BUCKET: str = "meeting-copilot-files"
    OSS_SECURE: bool = False

    # LLM配置
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "Qwen3-32B"
    LLM_API_ENDPOINT: str = ""
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 16384
    LLM_TIMEOUT: int = 900        # 单次 LLM 请求超时（秒）；长会议纪要生成需要较长时间
    LLM_MAX_RETRIES: int = 2      # 单次 LLM 请求内部的失败重试次数

    # ASR配置
    ASR_API_URL: str = ""
    ASR_API_KEY: str = ""

    # 是否允许 LLM / ASR 指向内网地址
    # True  = 允许 RFC1918(10/8、172.16/12、192.168/16) 与 fc00::/7
    #          （ASR/LLM 常部署在本机或内网，这是本项目的常态）
    # False = 完全禁止所有内网地址
    # 无论开关如何：回环(127/8、::1)、链路本地(169.254/16，含云元数据)、
    #              非 http(s) 协议永远拒绝
    ALLOW_INTERNAL_SERVICE_URLS: bool = True

    # 会话配置
    SESSION_EXPIRE_HOURS: int = 8  # 登录后 8 小时要求重新登录

    # HMAC 签名密钥（用于 X-User-Info token 防伪造；必填，无默认值）
    AUTH_SECRET: str = ""

    # 默认管理员（首次启动自动 seed；账号和密码必填，不允许默认值）
    DEFAULT_ADMIN_USER: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = ""
    DEFAULT_ADMIN_NAME: str = "超级管理员"

    # OA 认证配置（留空则关闭 OA 登录，只走本地账号）
    OA_BASE_URL: str = ""          # OA 系统地址，如 http://oa.company.com:8000
    OA_API_IDENTIFIER: str = ""    # OA 侧分配的应用标识
    OA_TIMEOUT: int = 10           # OA 接口超时（秒）

    # 会议模板配置
    MEETING_TEMPLATES_PATH: str = "./meeting_summary_templates.json"

    # 分页配置
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # CORS配置
    CORS_ORIGINS: str = "http://localhost:8888,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list:
        """将CORS_ORIGINS字符串解析为列表"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_required(self) -> "Settings":
        """启动时校验必填配置，并对密文密码进行解密"""
        raw = self.DB_PASSWORD_ENCRYPTED or ""
        if raw.startswith("enc:"):
            if not self.DB_SECRET_KEY:
                raise ValueError(
                    "DB_PASSWORD_ENCRYPTED 以 'enc:' 开头时必须同时设置 DB_SECRET_KEY"
                )
            try:
                from cryptography.fernet import Fernet, InvalidToken
                fernet = Fernet(self.DB_SECRET_KEY.encode("utf-8"))
                self.DB_PASSWORD = fernet.decrypt(
                    raw[4:].encode("utf-8")
                ).decode("utf-8")
            except InvalidToken:
                raise ValueError(
                    "DB_PASSWORD_ENCRYPTED 解密失败：DB_SECRET_KEY 不正确或密文已损坏"
                )
        elif raw:
            self.DB_PASSWORD = raw

        missing = []
        if not self.DB_PASSWORD:
            missing.append("DB_PASSWORD_ENCRYPTED")
        if not self.AUTH_SECRET:
            missing.append("AUTH_SECRET")
        if not self.DEFAULT_ADMIN_PASSWORD:
            missing.append("DEFAULT_ADMIN_PASSWORD")
        if missing:
            raise ValueError(f"缺少必填配置: {', '.join(missing)}，请检查 .env 文件")
        return self

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()