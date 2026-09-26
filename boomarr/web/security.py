"""Authentication, sessions and request hardening for the web layer."""

import base64
import binascii
import hmac
import ipaddress
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from boomarr.const import ENV_API_KEY, ENV_WEBHOOK_API_KEY, AuthMethod

if TYPE_CHECKING:  # pragma: no cover
    from boomarr.daemon import Daemon

SESSION_COOKIE = "boomarr_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "boomarr"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Principal:
    """Who is making a request, and how they were authenticated."""

    name: str
    method: str  # session, oidc, api_key, external, local, none

    @property
    def uses_cookie(self) -> bool:
        return self.method in {"session", "oidc"}


# ---------------------------------------------------------------------------
# Client address handling (reverse proxies)
# ---------------------------------------------------------------------------


def parse_networks(
    values: list[str],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(v, strict=False) for v in values]


def _ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None


def in_networks(value: str | None, networks: list[Any]) -> bool:
    address = _ip(value) if value else None
    return address is not None and any(address in net for net in networks)


def is_local_address(value: str | None) -> bool:
    """Loopback, private (RFC 1918/ULA) or link-local address."""
    address = _ip(value) if value else None
    if address is None:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_private or address.is_loopback or address.is_link_local


class ProxyHeadersMiddleware:
    """Resolve the real client address/scheme behind trusted reverse proxies.

    The direct peer is kept in ``scope["boomarr.peer"]`` so that header-based
    (forward auth) authentication can verify that it really came from a
    trusted proxy.
    """

    def __init__(self, app: ASGIApp, trusted: list[str]) -> None:
        self.app = app
        self.trusted = parse_networks(trusted)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            client = scope.get("client")
            peer = client[0] if client else None
            scope["boomarr.peer"] = peer
            if peer and self.trusted and in_networks(peer, self.trusted):
                headers = {k.lower(): v for k, v in scope.get("headers", [])}
                forwarded_for = headers.get(b"x-forwarded-for", b"").decode("latin-1")
                hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
                # Right-most address that is not one of our proxies.
                for hop in reversed(hops):
                    if not in_networks(hop, self.trusted):
                        scope["client"] = (hop, 0)
                        break
                proto = headers.get(b"x-forwarded-proto", b"").decode("latin-1")
                if proto in {"http", "https"}:
                    scope["scheme"] = proto
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Adds conservative security headers to every response."""

    _HEADERS: ClassVar[list[tuple[bytes, bytes]]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"same-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        (
            b"content-security-policy",
            b"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            b"script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            b"form-action 'self'",
        ),
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers.extend(h for h in self._HEADERS if h[0] not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionManager:
    """Signed, stateless session cookies bound to the credential version.

    ``max_age_days`` is a callable so that changing ``auth.session_days`` in
    the UI takes effect immediately.
    """

    def __init__(self, secret: str, max_age_days: Callable[[], int], path: str) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt="boomarr.session")
        self._oidc = URLSafeTimedSerializer(secret, salt="boomarr.oidc")
        self._max_age_days = max_age_days
        self.path = path or "/"

    @property
    def max_age(self) -> int:
        return self._max_age_days() * 86400

    def issue(
        self,
        response: Response,
        request: Request,
        payload: dict[str, Any],
        *,
        persistent: bool = True,
    ) -> None:
        token = self._serializer.dumps(payload)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=self.max_age if persistent else None,
            path=self.path,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )

    def read(self, request: Request) -> dict[str, Any] | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        try:
            data = self._serializer.loads(token, max_age=self.max_age)
        except BadSignature:
            return None
        return data if isinstance(data, dict) else None

    def clear(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path=self.path)

    def dump_oidc(self, data: dict[str, Any]) -> str:
        return self._oidc.dumps(data)

    def load_oidc(self, token: str, max_age: int = 600) -> dict[str, Any] | None:
        try:
            data = self._oidc.loads(token, max_age=max_age)
        except BadSignature:
            return None
        return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Login rate limiting
# ---------------------------------------------------------------------------


class LoginThrottle:
    """Locks an address out after too many failed logins."""

    def __init__(self, max_failures: int = 5, window: float = 300.0) -> None:
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        attempts = self._failures[key]
        while attempts and now - attempts[0] > self.window:
            attempts.popleft()
        return attempts

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        attempts = self._prune(key, now)
        if len(attempts) < self.max_failures:
            return 0
        return int(self.window - (now - attempts[0])) + 1

    def failure(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now).append(now)

    def success(self, key: str) -> None:
        self._failures.pop(key, None)


# ---------------------------------------------------------------------------
# Principal resolution
# ---------------------------------------------------------------------------


def request_api_key(request: Request) -> str | None:
    """Extract an API key from header, query, bearer token or basic auth."""
    if key := request.headers.get("x-api-key"):
        return key
    if key := request.query_params.get("apikey"):
        return key
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and credentials:
        return credentials
    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
        except binascii.Error, UnicodeDecodeError:
            return None
        return decoded.partition(":")[2] or None
    return None


def effective_api_key(daemon: Daemon) -> str:
    """Configured key > environment > generated key in ``auth.json``."""
    configured = daemon.config.server.api_key
    if configured is not None:
        return configured.get_secret_value()
    return (
        os.environ.get(ENV_API_KEY)
        or os.environ.get(ENV_WEBHOOK_API_KEY)
        or daemon.auth.api_key
    )


def client_host(request: Request) -> str | None:
    return request.client.host if request.client else None


def resolve_principal(request: Request) -> Principal | None:
    daemon: Daemon = request.app.state.daemon
    sessions: SessionManager = request.app.state.sessions
    auth = daemon.config.auth

    key = request_api_key(request)
    if key is not None:
        expected = effective_api_key(daemon)
        if hmac.compare_digest(key.encode(), expected.encode()):
            return Principal("api", "api_key")
        return None

    if auth.method == AuthMethod.NONE:
        return Principal("anonymous", "none")
    if auth.local_bypass and is_local_address(client_host(request)):
        return Principal("local", "local")
    if auth.method == AuthMethod.EXTERNAL:
        peer = request.scope.get("boomarr.peer")
        trusted = parse_networks(daemon.config.server.trusted_proxies)
        user = request.headers.get(auth.external_header)
        if user and in_networks(peer, trusted):
            return Principal(user, "external")
        return None

    session = sessions.read(request)
    if session and session.get("v") == daemon.auth.session_version:
        return Principal(str(session.get("u")), str(session.get("m", "session")))
    return None


async def require_user(request: Request) -> Principal:
    """FastAPI dependency: an authenticated principal (with CSRF check)."""
    principal = resolve_principal(request)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    if (
        principal.uses_cookie
        and request.method not in _SAFE_METHODS
        and request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing CSRF header")
    return principal
