"""Bounded, read-only public collection with DNS-pinned HTTPS connections.

Injected transports/resolvers are trusted test seams. The default transport resolves,
validates every returned address, and connects to a numeric public IP while HTTP
Host and TLS SNI retain the approved hostname. Preflight checks alone are insufficient.
"""

import asyncio
import hashlib
import ipaddress
import re
import socket
import ssl
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpcore2
import httpx2 as httpx
from bs4 import BeautifulSoup
from pydantic import Field

from telescope_rag.core.settings import PUBLIC_HOSTS, Settings
from telescope_rag.ingestion.models import RawPage, Record, stable_id

BOT = "TelescopePublicKnowledgeBot"
Resolver = Callable[[str], Awaitable[Sequence[str]]]
Sleep = Callable[[float], Awaitable[None]]
PRIVATE_SEGMENTS = frozenset(
    {
        "patient",
        "patients",
        "patient-report",
        "patient-reports",
        "patient-portal",
        "report",
        "reports",
        "portal",
        "login",
        "logout",
        "signin",
        "sign-in",
        "wp-admin",
        "wp-login.php",
        "wp-json",
        "admin",
        "administrator",
        "private",
        "account",
        "my-account",
        "dashboard",
        "calendar",
        "schedule",
        "schedules",
        "appointment",
        "appointments",
        "booking",
        "book",
        "book-appointment",
        "form",
        "forms",
        "submit",
        "checkout",
        "cart",
        "register",
        "registration",
        "request-medical-report",
        "medical-request-report",
        "medical-report",
        "medical-reports",
        "testimonial",
        "testimonials",
        "suggestions-complaints",
        "international-patients-form",
    }
)
NON_HTML_SUFFIXES = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
        ".css",
        ".js",
        ".woff",
        ".woff2",
        ".ttf",
        ".mp4",
        ".zip",
        ".pdf",
        ".xml",
        ".txt",
    }
)


class CollectionError(Exception):
    """Fixed safe error code, without URL input or upstream content."""


class CollectionLimits(Record):
    max_requests: int = Field(default=1024, ge=1, le=1024)
    max_discoveries: int = Field(default=5000, ge=1, le=5000)
    max_links_per_page: int = Field(default=1000, ge=1, le=1000)
    max_link_occurrences: int = Field(default=50000, ge=1, le=50000)
    max_records: int = Field(default=50000, ge=1, le=50000)
    max_sitemaps: int = Field(default=20, ge=0, le=20)
    max_sitemap_depth: int = Field(default=3, ge=0, le=3)
    max_redirects: int = Field(default=5, ge=0, le=5)
    timeout_seconds: float = Field(default=15, gt=0, le=30)
    max_elapsed_seconds: float = Field(default=600, gt=0, le=3600)
    max_control_bytes: int = Field(default=262144, ge=1, le=262144)


class CollectionRecord(Record):
    reference_id: str
    url: str | None = None
    source_url: str | None = None
    kind: Literal["page", "robots", "sitemap", "redirect"]
    outcome: Literal["collected", "duplicate", "disallowed", "failed", "deferred"]
    code: str
    depth: int = Field(default=0, ge=0)
    occurrence_index: int | None = Field(default=None, ge=0)
    status_code: int | None = None
    fetched_at: datetime | None = None
    content_type: str | None = None
    byte_count: int | None = None
    content_hash: str | None = None
    final_url: str | None = None


class CollectionManifest(Record):
    snapshot_id: str
    started_at: datetime
    completed_at: datetime
    collector_version: str = "public-static-pinned-v2"
    approved: bool = False
    coverage_complete: bool
    coverage_gaps: tuple[str, ...]
    records: tuple[CollectionRecord, ...]
    pages: tuple[RawPage, ...] = Field(repr=False)
    limits: CollectionLimits


def canonical_url(
    value: str, *, base: str | None = None, allowed_hosts: Iterable[str] = PUBLIC_HOSTS
) -> str:
    """Conservative identity: language, case, and trailing slash remain distinct."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise CollectionError("invalid_url")
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise CollectionError("invalid_url")
    parsed = urlsplit(urljoin(base, value) if base else value)
    try:
        port = parsed.port
    except ValueError:
        raise CollectionError("unsafe_port") from None
    if parsed.scheme != "https" or parsed.hostname not in set(allowed_hosts):
        raise CollectionError("unapproved_origin")
    if port not in (None, 443) or parsed.username is not None or parsed.password is not None:
        raise CollectionError("unsafe_authority")
    if parsed.query:
        raise CollectionError("query_not_collected")
    path = parsed.path or "/"
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeError:
        raise CollectionError("ambiguous_path") from None
    if (
        "%" in decoded
        or "\\" in decoded
        or "//" in decoded
        or ";" in decoded
        or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
    ):
        raise CollectionError("ambiguous_path")
    segments = decoded.strip("/").casefold().split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise CollectionError("ambiguous_path")
    if any(segment in PRIVATE_SEGMENTS or segment.endswith("-form") for segment in segments):
        raise CollectionError("excluded_private_or_action_route")
    if re.search(
        r"(?:^|/)(?:patient|book|booking|appointment|admin|login|submit|form)[-_]",
        decoded.casefold(),
    ):
        raise CollectionError("excluded_private_or_action_route")
    path = quote(decoded, safe="/!$&'()*+,-.:;=@_~")
    return urlunsplit(("https", parsed.hostname, path, "", ""))


async def resolve_public(host: str) -> Sequence[str]:
    records = await asyncio.get_running_loop().getaddrinfo(
        host, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
    )
    return tuple(dict.fromkeys(record[4][0] for record in records))


def _public_addresses(addresses: Sequence[str]) -> tuple[str, ...]:
    if not addresses:
        raise CollectionError("dns_empty")
    validated = []
    for text in addresses:
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            raise CollectionError("dns_invalid_address") from None
        if (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or getattr(address, "ipv4_mapped", None) is not None
        ):
            raise CollectionError("dns_non_public")
        validated.append(str(address))
    return tuple(dict.fromkeys(validated))


class PinnedPublicBackend(httpcore2.AsyncNetworkBackend):
    """Connect to validated numeric addresses; TLS still authenticates the URL host."""

    def __init__(
        self,
        resolver: Resolver = resolve_public,
        *,
        backend: httpcore2.AsyncNetworkBackend | None = None,
        allowed_hosts: Iterable[str] = PUBLIC_HOSTS,
    ):
        self.resolver = resolver
        self.backend = backend if backend is not None else httpcore2.AnyIOBackend()
        self.allowed_hosts = frozenset(allowed_hosts)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore backend interface.
        local_address: str | None = None,
        socket_options=None,
    ):
        if host not in self.allowed_hosts or port != 443 or local_address is not None:
            raise CollectionError("unsafe_connection_target")
        addresses = _public_addresses(await self.resolver(host))
        return await self.backend.connect_tcp(
            addresses[0], port, timeout=timeout, local_address=None, socket_options=socket_options
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise CollectionError("unix_connections_forbidden")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _CoreStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for part in self.stream:
            yield part

    async def aclose(self):
        if hasattr(self.stream, "aclose"):
            await self.stream.aclose()


class PinnedPublicTransport(httpx.AsyncBaseTransport):
    def __init__(
        self, resolver: Resolver = resolve_public, *, allowed_hosts: Iterable[str] = PUBLIC_HOSTS
    ):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.pool = httpcore2.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            retries=0,
            max_connections=1,
            max_keepalive_connections=0,
            http2=False,
            network_backend=PinnedPublicBackend(resolver, allowed_hosts=self.allowed_hosts),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        canonical_url(str(request.url), allowed_hosts=self.allowed_hosts)
        if request.method != "GET":
            raise CollectionError("only_get_allowed")
        response = await self.pool.handle_async_request(
            httpcore2.Request(
                method=request.method,
                url=httpcore2.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_CoreStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


@dataclass(frozen=True)
class _Fetched:
    url: str
    status: int
    content_type: str
    body: bytes
    fetched_at: datetime


@dataclass(frozen=True)
class _RobotPolicy:
    rules: tuple[tuple[str, bool], ...]

    def allows(self, url: str) -> bool:
        path = urlsplit(url).path or "/"
        matches = []
        for pattern, allow in self.rules:
            exact = pattern.endswith("$")
            prefix = pattern[:-1] if exact else pattern
            if (exact and path == prefix) or (not exact and path.startswith(prefix)):
                matches.append((len(prefix), allow))
        return max(matches, default=(0, True))[1]


def _robot_policy(text: str) -> _RobotPolicy:
    """Longest applicable literal rule; unsupported patterns deny the host.

    urllib.robotparser is used only for rate hints: its first-match authorization
    can permit a less specific Allow before a more specific Disallow.
    """
    groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, bool]] = []
    has_directives = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.casefold()
        if key == "user-agent":
            if has_directives:
                groups.append((agents, rules))
                agents, rules, has_directives = [], [], False
            if not value:
                raise CollectionError("robots_unsupported")
            agents.append(value.casefold())
        elif key in {"allow", "disallow"}:
            if not agents:
                raise CollectionError("robots_unsupported")
            has_directives = True
            if value:
                rules.append((value, key == "allow"))
        elif agents and key not in {"sitemap"}:
            has_directives = True
    groups.append((agents, rules))
    candidates = []
    for group_agents, group_rules in groups:
        specificity = max(
            (
                0 if agent == "*" else len(agent)
                for agent in group_agents
                if agent == "*" or agent in BOT.casefold()
            ),
            default=-1,
        )
        if specificity >= 0:
            candidates.append((specificity, group_rules))
    selected = max((score for score, _ in candidates), default=-1)
    applicable = tuple(rule for score, group in candidates if score == selected for rule in group)
    if len(applicable) > 1024:
        raise CollectionError("robots_unsupported")
    for pattern, _ in applicable:
        if (
            not pattern.startswith("/")
            or len(pattern) > 4096
            or "*" in pattern
            or "%" in pattern
            or "$" in pattern[:-1]
            or not pattern.isascii()
            or any(ord(char) < 32 for char in pattern)
        ):
            raise CollectionError("robots_unsupported")
    return _RobotPolicy(applicable)


class _Collector:
    def __init__(
        self,
        settings: Settings,
        directory: Path,
        snapshot_id: str,
        *,
        transport: httpx.AsyncBaseTransport | None,
        resolver: Resolver,
        limits: CollectionLimits,
        sleep: Sleep,
    ):
        self.settings, self.directory, self.snapshot_id = settings, directory, snapshot_id
        self.limits, self.resolver, self.sleep = limits, resolver, sleep
        self.allowed_hosts = frozenset(settings.crawl_allowed_hosts)
        self.client = httpx.AsyncClient(
            transport=transport
            if transport is not None
            else PinnedPublicTransport(resolver, allowed_hosts=self.allowed_hosts),
            trust_env=False,
            follow_redirects=False,
            timeout=limits.timeout_seconds,
            headers={
                "User-Agent": BOT,
                "Accept-Encoding": "identity",
                "Accept": "text/html,application/xhtml+xml,text/plain,application/xml",
            },
        )
        self.started_at = datetime.now(UTC)
        self.deadline = time.monotonic() + limits.max_elapsed_seconds
        self.requests = 0
        self.last_request: dict[str, float] = {}
        self.robots: dict[str, _RobotPolicy | None] = {}
        self.delays: dict[str, float] = {}
        self.records: list[CollectionRecord] = []
        self.gaps: list[str] = []
        self.pages: list[RawPage] = []
        self.queue: deque[tuple[str, int, str | None]] = deque()
        self.discovered: set[str] = set()
        self.discovery_references: set[str] = set()
        self.link_occurrences = 0
        self.sitemaps: deque[tuple[str, int]] = deque()
        self.seen_sitemaps: set[str] = set()
        self.seen_pages: set[str] = set()

    def record(
        self,
        value: str,
        kind: str,
        outcome: str,
        code: str,
        *,
        source: str | None = None,
        depth: int = 0,
        occurrence_index: int | None = None,
        fetched: _Fetched | None = None,
    ):
        if len(self.records) >= self.limits.max_records:
            self.gap("record_limit")
            return
        # Never persist rejected credentials/query values or off-domain URLs.
        try:
            safe_url = canonical_url(value, allowed_hosts=self.allowed_hosts)
        except (CollectionError, ValueError):
            safe_url = None
        self.records.append(
            CollectionRecord(
                reference_id=stable_id(value),
                url=safe_url,
                source_url=source,
                kind=kind,
                outcome=outcome,
                code=code,
                depth=depth,
                occurrence_index=occurrence_index,
                status_code=fetched.status if fetched else None,
                fetched_at=fetched.fetched_at if fetched else None,
                content_type=fetched.content_type if fetched else None,
                byte_count=len(fetched.body) if fetched else None,
                content_hash=hashlib.sha256(fetched.body).hexdigest() if fetched else None,
                final_url=fetched.url if fetched else None,
            )
        )

    def gap(self, code: str):
        if code not in self.gaps:
            self.gaps.append(code)

    def discover(
        self, value: str, *, base: str | None, depth: int, occurrence_index: int | None = None
    ):
        absolute = urljoin(base, value) if base else value
        error = None
        try:
            url = canonical_url(absolute, allowed_hosts=self.allowed_hosts)
        except (CollectionError, ValueError) as exc:
            url = None
            error = str(exc) if isinstance(exc, CollectionError) else "invalid_url"
        reference = stable_id(url if url is not None else absolute)
        if reference not in self.discovery_references:
            if len(self.discovery_references) >= self.limits.max_discoveries:
                self.gap("discovery_limit")
                self.record(
                    url or absolute,
                    "page",
                    "deferred",
                    "discovery_limit",
                    source=base,
                    depth=depth,
                    occurrence_index=occurrence_index,
                )
                return
            self.discovery_references.add(reference)
        if error is not None:
            self.record(
                absolute,
                "page",
                "disallowed",
                error,
                source=base,
                depth=depth,
                occurrence_index=occurrence_index,
            )
            return
        if Path(urlsplit(url).path).suffix.casefold() in NON_HTML_SUFFIXES:
            self.record(
                url,
                "page",
                "disallowed",
                "unsupported_resource",
                source=base,
                depth=depth,
                occurrence_index=occurrence_index,
            )
        elif url in self.discovered:
            self.record(
                url,
                "page",
                "duplicate",
                "already_discovered",
                source=base,
                depth=depth,
                occurrence_index=occurrence_index,
            )
        elif depth > min(self.settings.crawl_max_depth, 4):
            self.record(
                url,
                "page",
                "deferred",
                "depth_limit",
                source=base,
                depth=depth,
                occurrence_index=occurrence_index,
            )
            self.gap("depth_limit")
        else:
            self.discovered.add(url)
            self.queue.append((url, depth, base))

    async def fetch(self, url: str, *, kind: str, check_robots: bool = True) -> _Fetched:
        visited = set()
        for redirect in range(self.limits.max_redirects + 1):
            url = canonical_url(url, allowed_hosts=self.allowed_hosts)
            if url in visited:
                raise CollectionError("redirect_cycle")
            visited.add(url)
            host = urlsplit(url).hostname
            if check_robots and not await self.permitted(url):
                raise CollectionError("robots_disallowed_or_unavailable")
            if self.requests >= self.limits.max_requests:
                raise CollectionError("request_limit")
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise CollectionError("collection_deadline")
            async with asyncio.timeout(min(remaining, self.limits.timeout_seconds)):
                # Each dispatch is checked even with a trusted mock transport. Production
                # connection pins its own fresh validated resolution in the backend.
                _public_addresses(await self.resolver(host))
                delay = max(self.settings.crawl_delay_seconds, self.delays.get(host, 0))
                wait = self.last_request.get(host, -float("inf")) + delay - time.monotonic()
                if wait > 0:
                    await self.sleep(wait)
                self.requests += 1
                self.last_request[host] = time.monotonic()
                async with self.client.stream("GET", url) as response:
                    cap = min(self.settings.crawl_max_page_bytes, 2000000)
                    if kind != "page":
                        cap = min(cap, self.limits.max_control_bytes)
                    encoding = response.headers.get("content-encoding", "identity").casefold()
                    if encoding not in {"", "identity"}:
                        raise CollectionError("compressed_response_not_accepted")
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isdecimal() or int(length) > cap):
                        raise CollectionError("body_limit")
                    body = bytearray()
                    async for part in response.aiter_bytes(chunk_size=65536):
                        if len(body) + len(part) > cap:
                            raise CollectionError("body_limit")
                        body.extend(part)
                    fetched = _Fetched(
                        url,
                        response.status_code,
                        response.headers.get("content-type", "").split(";", 1)[0].strip().lower(),
                        bytes(body),
                        datetime.now(UTC),
                    )
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        return fetched
                    location = response.headers.get("location")
                    if not location or redirect == self.limits.max_redirects:
                        raise CollectionError("redirect_limit_or_missing_location")
                    next_url = canonical_url(location, base=url, allowed_hosts=self.allowed_hosts)
                    self.record(url, "redirect", "collected", "validated_redirect", fetched=fetched)
                    url = next_url
        raise CollectionError("redirect_limit")

    async def permitted(self, url: str) -> bool:
        host = urlsplit(url).hostname
        if host not in self.robots:
            # A sentinel prevents recursion; robots fetches never follow page permission.
            self.robots[host] = None
            robots_url = f"https://{host}/robots.txt"
            try:
                fetched = await self.fetch(robots_url, kind="robots", check_robots=False)
                parser = RobotFileParser()
                parser.set_url(robots_url)
                if fetched.status == 404:
                    parser.parse([])
                    policy = _RobotPolicy(())
                elif fetched.status == 200 and fetched.content_type in {"text/plain", ""}:
                    text = fetched.body.decode("utf-8", errors="strict")
                    parser.parse(text.splitlines())
                    policy = _robot_policy(text)
                    for line in text.splitlines():
                        if line.split(":", 1)[0].strip().casefold() == "sitemap":
                            location = line.split(":", 1)[1].strip()
                            if len(self.sitemaps) < self.limits.max_discoveries:
                                self.sitemaps.append((location, 0))
                            else:
                                self.gap("discovery_limit")
                else:
                    raise CollectionError("robots_unavailable")
                self.robots[host] = policy
                crawl_delay = parser.crawl_delay(BOT)
                rate = parser.request_rate(BOT)
                declared_delays = [
                    float(value)
                    for value in re.findall(
                        r"(?im)^\s*crawl-delay\s*:\s*(\d+(?:\.\d+)?)\s*(?:#.*)?$",
                        fetched.body.decode("utf-8", errors="strict"),
                    )
                ]
                self.delays[host] = max(
                    crawl_delay or 0,
                    rate.seconds / rate.requests if rate and rate.requests else 0,
                    *declared_delays,
                )
                self.record(robots_url, "robots", "collected", "robots_loaded", fetched=fetched)
                if fetched.status == 404:
                    self.sitemaps.append((f"https://{host}/sitemap.xml", 0))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.record(robots_url, "robots", "failed", _error_code(exc))
                self.gap("robots_unavailable")
        parser = self.robots[host]
        return parser is not None and parser.allows(url)

    async def collect_sitemaps(self):
        while self.sitemaps:
            raw_url, depth = self.sitemaps.popleft()
            try:
                url = canonical_url(raw_url, allowed_hosts=self.allowed_hosts)
            except (CollectionError, ValueError) as exc:
                self.record(raw_url, "sitemap", "disallowed", _error_code(exc))
                continue
            if url in self.seen_sitemaps:
                self.record(url, "sitemap", "duplicate", "already_discovered")
                continue
            if (
                len(self.seen_sitemaps) >= self.limits.max_sitemaps
                or depth > self.limits.max_sitemap_depth
            ):
                self.record(url, "sitemap", "deferred", "sitemap_limit")
                self.gap("sitemap_limit")
                continue
            self.seen_sitemaps.add(url)
            try:
                fetched = await self.fetch(url, kind="sitemap")
                if fetched.status == 404:
                    self.record(url, "sitemap", "failed", "sitemap_not_found", fetched=fetched)
                    continue
                if fetched.status != 200:
                    raise CollectionError("sitemap_http_error")
                if fetched.content_type not in {"application/xml", "text/xml", ""}:
                    raise CollectionError("sitemap_content_type")
                text = fetched.body.decode("utf-8-sig", errors="strict")
                if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, flags=re.I):
                    raise CollectionError("sitemap_entities_forbidden")
                root = ET.fromstring(text)
                tag = root.tag.rsplit("}", 1)[-1]
                if tag not in {"sitemapindex", "urlset"}:
                    raise CollectionError("sitemap_invalid_root")
                child_kind = "sitemap" if tag == "sitemapindex" else "url"
                for child in root:
                    if child.tag.rsplit("}", 1)[-1] != child_kind:
                        continue
                    locations = [
                        item.text for item in child if item.tag.rsplit("}", 1)[-1] == "loc"
                    ]
                    if len(locations) != 1 or not locations[0]:
                        self.gap("sitemap_invalid_entry")
                        continue
                    if tag == "sitemapindex":
                        if len(self.sitemaps) < self.limits.max_discoveries:
                            self.sitemaps.append((locations[0].strip(), depth + 1))
                        else:
                            self.gap("discovery_limit")
                    else:
                        self.discover(locations[0].strip(), base=url, depth=0)
                self.record(url, "sitemap", "collected", "sitemap_parsed", fetched=fetched)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.record(url, "sitemap", "failed", _error_code(exc))
                self.gap("sitemap_failure")

    async def run(self, seeds: Sequence[str]) -> CollectionManifest:
        for seed in seeds:
            self.discover(seed, base=None, depth=0)
        page_attempts = 0
        try:
            while self.queue:
                url, depth, source = self.queue.popleft()
                if page_attempts >= min(self.settings.crawl_max_pages, 250):
                    self.record(url, "page", "deferred", "page_limit", source=source, depth=depth)
                    self.gap("page_limit")
                    continue
                page_attempts += 1
                fetched = None
                try:
                    fetched = await self.fetch(url, kind="page")
                    if fetched.status != 200:
                        raise CollectionError("page_http_error")
                    if fetched.content_type not in {"text/html", "application/xhtml+xml"}:
                        raise CollectionError("page_content_type")
                    # UTF-8 is required; do not silently replace corrupt source evidence.
                    html = fetched.body.decode("utf-8-sig", errors="strict")
                    if fetched.url in self.seen_pages:
                        self.record(
                            url, "page", "duplicate", "redirected_duplicate", fetched=fetched
                        )
                        continue
                    self.seen_pages.add(fetched.url)
                    page = RawPage(
                        snapshot_id=self.snapshot_id,
                        document_id=stable_id(fetched.url),
                        canonical_url=fetched.url,
                        fetched_at=fetched.fetched_at,
                        content_hash=hashlib.sha256(fetched.body).hexdigest(),
                        html=html,
                    )
                    _exclusive_json(self.directory / "raw" / f"{page.document_id}.json", page)
                    with (self.directory / "raw" / f"{page.document_id}.html").open("xb") as handle:
                        handle.write(fetched.body)
                    self.pages.append(page)
                    self.record(
                        url,
                        "page",
                        "collected",
                        "html_snapshot",
                        source=source,
                        depth=depth,
                        fetched=fetched,
                    )
                    soup = BeautifulSoup(html, "html.parser")
                    # Ignore HTML <base>, forms, and script-generated navigation.
                    for index, link in enumerate(
                        soup.find_all("a", href=True, limit=self.limits.max_links_per_page + 1)
                    ):
                        if index >= self.limits.max_links_per_page:
                            self.gap("page_link_occurrence_limit")
                            self.record(
                                fetched.url,
                                "page",
                                "deferred",
                                "page_link_occurrence_limit",
                                source=fetched.url,
                                occurrence_index=index,
                            )
                            break
                        if self.link_occurrences >= self.limits.max_link_occurrences:
                            self.gap("link_occurrence_limit")
                            self.record(
                                fetched.url,
                                "page",
                                "deferred",
                                "link_occurrence_limit",
                                source=fetched.url,
                                occurrence_index=index,
                            )
                            break
                        self.link_occurrences += 1
                        if link.find_parent("form") is None:
                            self.discover(
                                str(link["href"]),
                                base=fetched.url,
                                depth=depth + 1,
                                occurrence_index=index,
                            )
                    if soup.find("script") and not soup.get_text(" ", strip=True):
                        self.gap("javascript_rendering_may_be_required")
                    await self.collect_sitemaps()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    code = _error_code(exc)
                    self.record(
                        url, "page", "failed", code, source=source, depth=depth, fetched=fetched
                    )
                    self.gap(code)
            await self.collect_sitemaps()
            if self.queue:
                # Sitemaps discovered during a final robots read can introduce pages.
                self.gap("late_discovered_pages")
                while self.queue:
                    url, depth, source = self.queue.popleft()
                    self.record(
                        url, "page", "deferred", "late_discovered_pages", source=source, depth=depth
                    )
        finally:
            await self.client.aclose()
        manifest = CollectionManifest(
            snapshot_id=self.snapshot_id,
            started_at=self.started_at,
            completed_at=datetime.now(UTC),
            coverage_complete=bool(self.pages) and not self.gaps,
            coverage_gaps=tuple(self.gaps),
            records=tuple(self.records),
            pages=tuple(self.pages),
            limits=self.limits,
        )
        _exclusive_json(self.directory / "manifest.json", manifest)
        return manifest


def _error_code(exc: Exception) -> str:
    if isinstance(exc, CollectionError):
        return str(exc)
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpcore2.TimeoutException)):
        return "fetch_timeout"
    if isinstance(exc, UnicodeError):
        return "source_encoding_invalid"
    if isinstance(exc, ET.ParseError):
        return "sitemap_xml_invalid"
    return "fetch_failed"


def _exclusive_json(path: Path, model: Record):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(model.model_dump_json(indent=2))
        handle.write("\n")


async def collect(
    settings: Settings,
    output_dir: Path,
    snapshot_id: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = resolve_public,
    seeds: Sequence[str] | None = None,
    limits: CollectionLimits | None = None,
    sleep: Sleep = asyncio.sleep,
) -> CollectionManifest:
    """Create exactly output_dir (must not exist), then immutable raw/ and manifest.

    Snapshot identifiers are metadata; they never form paths. Requests are sequential,
    within the configured concurrency cap. This is source collection, never admission
    approval, paid embedding, indexing, or chatbot inference.
    """
    if not snapshot_id or len(snapshot_id) > 128 or any(ord(c) < 32 for c in snapshot_id):
        raise CollectionError("invalid_snapshot_id")
    directory = Path(output_dir)
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=False)
    await asyncio.to_thread((directory / "raw").mkdir)
    base = str(settings.website_base_url)
    selected_seeds = (
        seeds
        if seeds is not None
        else (
            base,
            urljoin(base, "/doctors/"),
            urljoin(base, "/contact-us/"),
            urljoin(base, "/faqs/"),
        )
    )
    if not selected_seeds:
        raise CollectionError("missing_seeds")
    collector = _Collector(
        settings,
        directory,
        snapshot_id,
        transport=transport,
        resolver=resolver,
        limits=limits or CollectionLimits(),
        sleep=sleep,
    )
    return await collector.run(selected_seeds)
