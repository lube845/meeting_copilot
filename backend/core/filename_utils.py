"""
文件名清洗 + Content-Disposition 构造（RFC 5987）

背景：
- Starlette 响应头按 latin-1 编码，中文文件名直接塞进 Content-Disposition 会抛
  UnicodeEncodeError（表现为 500）。中文必须 percent-encode 后用 filename* 传。
- Meeting.file_name 来自客户端输入（/meetings/init-upload），未过滤引号/换行/
  控制字符，存在 header 注入与存储脏数据的风险。
"""
from __future__ import annotations

import re
from urllib.parse import quote

# 控制字符 / 引号 / 反斜杠
_ILLEGAL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f"\'\\]')
# ASCII 兜底名允许的字符
_ASCII_FALLBACK_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str | None, max_len: int = 200, default: str = "meeting") -> str:
    """清洗客户端提供的文件名：去目录、去控制字符与引号、限长"""
    if not name:
        return default
    # 只保留最后一段，兼容 / 与 \ 两种分隔符
    name = name.replace("\\", "/").split("/")[-1]
    name = _ILLEGAL_CHARS_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:max_len].strip()
    return name or default


def build_content_disposition(
    filename: str,
    disposition: str = "attachment",
    fallback: str = "download",
) -> str:
    """构造带 ASCII 兜底名 + RFC 5987 filename* 的 Content-Disposition 头值

    Args:
        filename: 展示给用户的文件名（可含中文）
        disposition: disposition 类型，默认 attachment
        fallback: ASCII 兜底文件名（不含扩展名时由调用方拼好）
    """
    safe = sanitize_filename(filename)
    ascii_name = _ASCII_FALLBACK_RE.sub("_", safe).strip("._-")
    if not ascii_name:
        ascii_name = fallback
    elif "." not in ascii_name and "." in safe:
        # 保住扩展名，避免老客户端存成无扩展名的文件
        ascii_name = ascii_name + "." + safe.rsplit(".", 1)[-1]
    quoted = quote(safe, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
