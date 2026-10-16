# -*- coding: utf-8 -*-
"""Windows 网卡信息获取：本机 IPv4、掩码、网关、广播地址。

优先使用 ctypes 调用 GetAdaptersInfo（无语言环境依赖），失败时退回
socket.gethostbyname_ex 并假设 /24 掩码。
"""

import ctypes
import socket
import struct
from dataclasses import dataclass, field


@dataclass
class IfaceInfo:
    ip: str
    netmask: str = "255.255.255.0"
    broadcast: str = ""
    gateway: str = ""
    desc: str = ""

    @property
    def subnet(self) -> str:
        """形如 192.168.1.0 的网络地址"""
        try:
            ip_i = struct.unpack(">I", socket.inet_aton(self.ip))[0]
            mask_i = struct.unpack(">I", socket.inet_aton(self.netmask))[0]
            return socket.inet_ntoa(struct.pack(">I", ip_i & mask_i))
        except Exception:
            return ""

    @property
    def prefix_len(self) -> int:
        try:
            mask_i = struct.unpack(">I", socket.inet_aton(self.netmask))[0]
            return bin(mask_i).count("1")
        except Exception:
            return 24


def _ctypes_get_adapters():
    """通过 IP_ADAPTER_INFO 枚举网卡。返回 (ifaces, gateways) 或抛异常。"""
    class IP_ADDRESS_STRING(ctypes.Structure):
        _fields_ = [("String", ctypes.c_char * 16)]

    class IP_ADDR_STRING(ctypes.Structure):
        _fields_ = [
            ("Next", ctypes.c_void_p),
            ("IpAddress", IP_ADDRESS_STRING),
            ("IpMask", IP_ADDRESS_STRING),
            ("Context", ctypes.c_ulong),
        ]

    class IP_ADAPTER_INFO(ctypes.Structure):
        _fields_ = [
            ("Next", ctypes.c_void_p),
            ("ComboIndex", ctypes.c_ulong),
            ("AdapterName", ctypes.c_char * 260),
            ("Description", ctypes.c_char * 132),
            ("AddressLength", ctypes.c_uint),
            ("Address", ctypes.c_ubyte * 8),
            ("Index", ctypes.c_ulong),
            ("Type", ctypes.c_uint),
            ("DhcpEnabled", ctypes.c_uint),
            ("CurrentIpAddress", ctypes.c_void_p),
            ("IpAddressList", IP_ADDR_STRING),
            ("GatewayList", IP_ADDR_STRING),
            ("DhcpServer", IP_ADDR_STRING),
            ("HaveWins", ctypes.c_int),
            ("PrimaryWinsServer", IP_ADDRESS_STRING),
            ("SecondaryWinsServer", IP_ADDRESS_STRING),
            ("LeaseObtained", ctypes.c_ulong),
            ("LeaseExpires", ctypes.c_ulong),
        ]

    ih = ctypes.windll.iphlpapi.GetAdaptersInfo
    size = ctypes.c_ulong(0)
    ih(None, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if ih(buf, ctypes.byref(size)) != 0:
        raise OSError("GetAdaptersInfo failed")
    ifaces = []
    gateways = set()
    p = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_INFO))
    while p:
        info = p.contents
        try:
            desc = info.Description.decode("gbk", "ignore")
        except Exception:
            desc = ""
        node = info.IpAddressList
        gw = info.GatewayList
        # 每张卡可能有多个 IP
        while True:
            ip = node.IpAddress.String.decode()
            mask = node.IpMask.String.decode()
            if ip and ip != "0.0.0.0":
                br = _broadcast_of(ip, mask)
                ifaces.append(IfaceInfo(ip=ip, netmask=mask or "255.255.255.0",
                                        broadcast=br, desc=desc))
            if not node.Next:
                break
            node = ctypes.cast(node.Next, ctypes.POINTER(IP_ADDR_STRING)).contents
        while True:
            g = gw.IpAddress.String.decode()
            if g and g != "0.0.0.0":
                gateways.add(g)
            if not gw.Next:
                break
            gw = ctypes.cast(gw.Next, ctypes.POINTER(IP_ADDR_STRING)).contents
        if not info.Next:
            break
        p = ctypes.cast(info.Next, ctypes.POINTER(IP_ADAPTER_INFO))
    return ifaces, gateways


def _broadcast_of(ip: str, mask: str) -> str:
    try:
        ip_i = struct.unpack(">I", socket.inet_aton(ip))[0]
        mask_i = struct.unpack(">I", socket.inet_aton(mask))[0]
        return socket.inet_ntoa(struct.pack(">I", ip_i | (~mask_i & 0xFFFFFFFF)))
    except Exception:
        return ""


# 虚拟网卡/隧道适配器特征关键词：代理软件（Clash/v2ray/sing-box TUN）、VPN、
# 虚拟机与 Hyper-V 虚拟交换机会创建这类网卡。它们不能承载局域网广播，
# 若不排除会导致设备发现失败（本机 IP 与广播地址取到虚拟网卡上）。
_VIRTUAL_DESC_KEYS = (
    "tun", "tap", "wintun", "wireguard", "openvpn", "vpn", "virtual",
    "vmware", "virtualbox", "hyper-v", "loopback", "pseudo",
    "zerotier", "tailscale", "radmin", "hamachi", "npcap", "bluetooth",
)


def _is_virtual(iface) -> bool:
    """判断是否为虚拟/隧道网卡（按描述名与 IP 段双重判定）"""
    desc = (getattr(iface, "desc", "") or "").lower()
    if any(k in desc for k in _VIRTUAL_DESC_KEYS):
        return True
    # 常见虚拟网段（即使描述名不含关键词也排除）
    ip = getattr(iface, "ip", "") or ""
    return ip.startswith(("198.18.", "198.19.", "28.", "169.254."))


def get_local_ifaces() -> list:
    """返回本机可用 IPv4 网卡列表（排除回环/虚拟网卡/未连接）"""
    try:
        ifaces, _gws = _ctypes_get_adapters()
        return [i for i in ifaces
                if not i.ip.startswith("127.") and not _is_virtual(i)]
    except Exception:
        out = []
        try:
            _h, _al, ips = socket.gethostbyname_ex(socket.gethostname())
            for ip in ips:
                if ":" in ip or ip.startswith("127."):
                    continue
                if ip.startswith(("198.18.", "198.19.", "28.", "169.254.")):
                    continue
                out.append(IfaceInfo(ip=ip, netmask="255.255.255.0",
                                     broadcast=_broadcast_of(ip, "255.255.255.0")))
        except Exception:
            pass
        return out


def get_gateways() -> list:
    try:
        _ifaces, gws = _ctypes_get_adapters()
        return sorted(gws)
    except Exception:
        return []


def get_local_ips() -> list:
    return [i.ip for i in get_local_ifaces()]
