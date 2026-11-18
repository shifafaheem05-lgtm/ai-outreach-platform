"""Outbound-connection guard: refuse hosts that resolve to private/loopback/link-local addresses."""
import ipaddress
import socket


def host_is_public(host: str, port: int = 443) -> bool:
    """True only if the host resolves and every address is globally routable."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)
