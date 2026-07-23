"""Network target safety helpers for outbound tools."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

RFC2544_BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")
RFC2544_FAKE_IP_COMPATIBILITY_REQUIRED = "FAKE_IP_COMPATIBILITY_REQUIRED"


def is_rfc2544_benchmark_address(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return whether an address belongs to the RFC 2544 benchmark range."""
    return isinstance(ip, ipaddress.IPv4Address) and ip in RFC2544_BENCHMARK_NETWORK


def _normalize_allowlist_entry(entry: str) -> tuple[str, int | None] | None:
    text = str(entry or "").strip().lower().rstrip("/")
    if not text:
        return None
    if "://" in text:
        parsed = urlparse(text)
        host = (parsed.hostname or "").strip().strip("[]").lower().rstrip(".")
        return (host, parsed.port) if host else None
    if text.startswith("[") and "]" in text:
        host, _, port_text = text[1:].partition("]")
        port = int(port_text[1:]) if port_text.startswith(":") and port_text[1:].isdigit() else None
        return host.strip().lower(), port
    host, sep, port_text = text.rpartition(":")
    if sep and port_text.isdigit() and "/" not in port_text:
        return host.strip().strip("[]").lower().rstrip("."), int(port_text)
    return text.strip("[]").lower().rstrip("."), None


def _allowlist_matches_host(
    *,
    host: str,
    port: int | None,
    allowlist: list[str] | tuple[str, ...] | None,
) -> bool:
    normalized_host = host.lower().rstrip(".")
    for raw_entry in allowlist or []:
        normalized = _normalize_allowlist_entry(raw_entry)
        if normalized is None:
            continue
        entry_host, entry_port = normalized
        if entry_port is not None and entry_port != port:
            continue
        if entry_host.startswith("*.") and normalized_host.endswith(entry_host[1:]):
            return True
        if entry_host == normalized_host:
            return True
    return False


def _allowlist_matches_ip(
    *,
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    port: int | None,
    allowlist: list[str] | tuple[str, ...] | None,
) -> bool:
    for raw_entry in allowlist or []:
        normalized = _normalize_allowlist_entry(raw_entry)
        if normalized is None:
            continue
        entry_host, entry_port = normalized
        if entry_port is not None and entry_port != port:
            continue
        try:
            if "/" in entry_host:
                if ip in ipaddress.ip_network(entry_host, strict=False):
                    return True
            elif ip == ipaddress.ip_address(entry_host):
                return True
        except ValueError:
            continue
    return False


def blocked_ip_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return a policy reason when an IP is not safe for generic web fetch."""
    if is_rfc2544_benchmark_address(ip):
        return "address is in the RFC 2544 benchmark range used by TUN fake-IP proxies"
    if not ip.is_global:
        return "address is not globally routable"
    return None


async def blocked_url_target_reason(
    url: str,
    *,
    allow_private_network: bool = False,
    private_network_allowlist: list[str] | tuple[str, ...] | None = None,
    allow_rfc2544_benchmark_range: bool = False,
) -> str | None:
    """Return a policy reason when a URL targets local/private networks."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().strip("[]").lower().rstrip(".")
    port = parsed.port
    if not host:
        return "URL must include a host."

    if allow_private_network and _allowlist_matches_host(
        host=host,
        port=port,
        allowlist=private_network_allowlist,
    ):
        return None

    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return f"host '{host}' resolves to a local-only name."

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if allow_private_network and _allowlist_matches_ip(
            ip=ip,
            port=port,
            allowlist=private_network_allowlist,
        ):
            return None
        return blocked_ip_reason(ip)

    loop = asyncio.get_running_loop()
    try:
        addr_info = await loop.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return None

    seen: set[str] = set()
    for *_, sockaddr in addr_info:
        address = str(sockaddr[0])
        if address in seen:
            continue
        seen.add(address)
        try:
            resolved_ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if allow_private_network and _allowlist_matches_ip(
            ip=resolved_ip,
            port=port,
            allowlist=private_network_allowlist,
        ):
            continue
        if allow_rfc2544_benchmark_range and is_rfc2544_benchmark_address(resolved_ip):
            continue
        reason = blocked_ip_reason(resolved_ip)
        if reason:
            return f"host '{host}' resolved to blocked address {resolved_ip} ({reason})."
    return None
