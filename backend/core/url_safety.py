"""
URL 安全校验：拒绝危险协议 / 本地 / 链路本地地址（防 SSRF）

两级策略：
- 「永远拒绝」（任何模式下都拒）：
  - 非 http/https 协议（file://、gopher:// 等经典 SSRF→RCE 向量）
  - 169.254.0.0/16（链路本地，含云元数据 169.254.169.254）、fe80::/10
  - 0.0.0.0/8、::/128（未指定地址）、多播与保留段
- 「内网 + 回环」：仅在 allow_private=False 时拒绝
  127.0.0.0/8、::1（回环）、10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、fc00::/7

allow_private=True 用于本项目常态：LLM / ASR 通常部署在 docker 网络(172.x)、
宿主机 LAN(192.168.x)、host.docker.internal，或与后端同机(127.0.0.1)。
allow_private=False 则完全禁止所有内网地址。
"""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


# 永远拒绝的网段
_ALWAYS_BLOCKED = [
    ipaddress.ip_network("0.0.0.0/8"),        # 未指定地址
    ipaddress.ip_network("::/128"),           # IPv6 未指定地址
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地（含云元数据 169.254.169.254）
    ipaddress.ip_network("fe80::/10"),        # IPv6 链路本地
    ipaddress.ip_network("224.0.0.0/4"),      # 多播
    ipaddress.ip_network("240.0.0.0/4"),      # 保留
]

# 内网 + 回环：allow_private=True 时放行
# 回环也归在这一档，是因为按 README 的开发方式后端跑在宿主机上，
# 此时 ASR/LLM 在 127.0.0.1:6028 是完全正常的用法，硬禁会把这条路径堵死。
_PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),      # IPv4 回环
    ipaddress.ip_network("::1/128"),          # IPv6 回环
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]


def _ip_is_blocked(ip_str: str, allow_private: bool) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 解析不出来按不安全处理
    if any(ip in net for net in _ALWAYS_BLOCKED):
        return True
    if not allow_private and any(ip in net for net in _PRIVATE_NETS):
        return True
    return False


def assert_safe_http_url(url: str, allow_private: bool = False) -> None:
    """校验 URL 协议为 http/https 且目标 IP 不在禁止网段；不通过抛 UnsafeURLError

    Args:
        url: 待校验的 URL
        allow_private: True 时允许内网段（RFC1918 / fc00::/7），回环 / 链路本地 /
            云元数据 / 非 http(s) 协议仍然拒绝。
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("URL 不能为空")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise UnsafeURLError(f"URL 解析失败: {e}")

    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"仅允许 http/https，收到 {parsed.scheme!r}")

    if not parsed.hostname:
        raise UnsafeURLError("URL 缺少主机名")

    # 已是字面 IP 的直接判定；否则解析所有 A/AAAA
    try:
        ipaddress.ip_address(parsed.hostname)
        addresses = [parsed.hostname]
    except ValueError:
        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror as e:
            raise UnsafeURLError(f"无法解析主机 {parsed.hostname!r}: {e}")
        addresses = list({i[4][0] for i in infos})

    for addr in addresses:
        if _ip_is_blocked(addr, allow_private):
            raise UnsafeURLError(f"URL 指向禁止访问的地址: {addr}")
