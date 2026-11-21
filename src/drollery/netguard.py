"""Keeps "add a link" from being used to reach the owner's own network.

Fetching a link means the server makes a request that somebody else chose. Without a check, a link such as
``http://192.168.1.1/admin``, ``http://localhost:8080/...`` or the cloud metadata address ``http://169.254.169.254/``
would make the server talk to things only it can reach. So by default a link is only fetched when every address its
host resolves to is a public one. This is checked when the link is added, again when the download runs, and for every
redirect that the direct download follows.

Two settings in ``config.toml`` relax it for people who want to fetch from their own network:
``allow_private_fetch = true`` switches the check off, and ``fetch_allow_hosts = ["nas.lan", "10.0.0.0/24"]`` lets
through just those hosts, addresses or networks.

This is a good defence against the straightforward cases, not a sandbox: a hostile DNS server that answers differently
between the check and the connection, or a downloader (yt-dlp, gallery-dl) that follows a redirect of its own, can still
get around it. For strong isolation run the container on a network that cannot reach your internal services.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from .config import get_settings
from .i18n import N_, t

BLOCKED = N_("This link points to a private or local network address ({host}), which Drollery does not fetch by default. To allow it, set allow_private_fetch or fetch_allow_hosts in config.toml")
NO_HOST = N_("That link has no address to fetch")
REDIRECTS = (301, 302, 303, 307, 308)
MAX_HOPS = 5
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_6TO4 = ipaddress.ip_network("2002::/16")


class BlockedAddress(Exception):
    """A link that points at a non-public address. str() is English (it ends up in job errors and the API);
    message() is translated for the person."""

    def __init__(self, host: str = ""):
        self.host = host
        super().__init__((BLOCKED if host else NO_HOST).format(host=host))

    def message(self) -> str:
        return t(BLOCKED, host=self.host) if self.host else t(NO_HOST)


def make_client() -> httpx.Client:                       # a seam for tests
    return httpx.Client(timeout=30)


def _resolve(host: str) -> list[str]:                    # a seam for tests
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(i[4][0]).split("%")[0] for i in infos})


def is_public(address: str) -> bool:
    """True only for an address on the public internet. Addresses that merely carry another one inside (IPv4-mapped,
    NAT64, 6to4) are judged by the address they carry."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.version == 6:
        if ip.ipv4_mapped:
            return is_public(str(ip.ipv4_mapped))
        if ip in _NAT64:
            return is_public(str(ipaddress.ip_address(int(ip) & 0xFFFFFFFF)))
        if ip in _6TO4:
            return is_public(str(ipaddress.ip_address((int(ip) >> 80) & 0xFFFFFFFF)))
    return ip.is_global and not ip.is_multicast


def _allowed(host: str, address: str | None) -> bool:
    """Is this host (or this address) on the owner's allow list?"""
    for entry in get_settings().fetch_allow_hosts:
        entry = str(entry).strip().lower().rstrip(".")
        if not entry:
            continue
        if address is None:
            if host == entry:
                return True
            continue
        try:
            if ipaddress.ip_address(address) in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            pass                                          # the entry is a name, not a network
    return False


def check_host(host: str) -> None:
    """Raise BlockedAddress unless the host resolves only to public addresses (or is allowed)."""
    if get_settings().allow_private_fetch:
        return
    host = (host or "").strip().strip("[]").rstrip(".").lower()
    if not host:
        raise BlockedAddress("")
    if _allowed(host, None):
        return
    try:
        addresses = _resolve(host)
    except OSError:
        return                                            # it does not resolve: the download fails by itself, nothing was reached
    if any(not is_public(a) and not _allowed(host, a) for a in addresses):
        raise BlockedAddress(host)


def check_url(url: str) -> None:
    check_host(urlparse(url).hostname or "")


def check_redirects(url: str) -> None:
    """Follow a link's redirects by hand (HEAD requests) and check every address on the way, so a public-looking link
    cannot bounce the server to an internal one. Used before handing a link to a downloader that follows its own
    redirects. A server that refuses HEAD or is unreachable simply ends the walk: the downloader will report that itself."""
    if get_settings().allow_private_fetch:
        return
    current = url
    with make_client() as client:
        for _ in range(MAX_HOPS):
            check_url(current)
            try:
                r = client.head(current, follow_redirects=False)
            except httpx.HTTPError:
                return
            location = r.headers.get("location")
            if r.status_code in REDIRECTS and location:
                current = urljoin(current, location)
                continue
            return
        check_url(current)
