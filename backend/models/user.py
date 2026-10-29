"""
用户数据模型（OA 风格标准账号，无 k 账号的强制改密/白名单机制）
"""
from sqlalchemy import Column, String, Boolean, DateTime
from backend.core.database import Base
from backend.core.datetime_utils import get_current_time


class User(Base):
    """本地账号表

    两种账号来源（auth_source）：
    - local：本地账号，用本地密码登录（seed 出来的 admin、兼底管理员）
    - oa   ：OA 账号，首次 OA 登录时自动建档；密码由 OA 校验，本地不存密码
    """
    __tablename__ = "users"

    loginid = Column(String(50), primary_key=True, comment="登录账号")
    password_hash = Column(String(255), nullable=False, default="", comment="PBKDF2 摘要（hex）；OA 账号为空")
    salt = Column(String(64), nullable=False, default="", comment="PBKDF2 盐（hex）；OA 账号为空")
    name = Column(String(64), nullable=True, comment="姓名")
    department = Column(String(64), nullable=True, comment="部门")
    job_title = Column(String(64), nullable=True, comment="岗位")
    auth_source = Column(
        String(20), nullable=False, default="local",
        comment="账号来源：local=本地密码，oa=OA 认证",
    )
    is_admin = Column(Boolean, default=False, nullable=False, comment="是否管理员")
    must_change_password = Column(Boolean, default=False, nullable=False, comment="是否强制改密")
    created_at = Column(DateTime, default=get_current_time, comment="创建时间")
    updated_at = Column(DateTime, default=get_current_time, onupdate=get_current_time, comment="更新时间")