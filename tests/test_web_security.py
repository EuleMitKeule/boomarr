"""Unit tests for boomarr.web.security."""

import asyncio
from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

from boomarr.web import security
from boomarr.web.security import (
    LoginThrottle,
    ProxyHeadersMiddleware,
    SecurityHeadersMiddleware,
    SessionManager,
    in_networks,
    is_local_address,
    parse_networks,
)


class TestAddresses:
    @pytest.mark.parametrize(
        ("address", "local"),
        [
            ("127.0.0.1", True),
            ("10.1.2.3", True),
            ("fe80::1", True),
            ("::ffff:192.168.1.1", True),
            ("::ffff:8.8.8.8", False),
            ("8.8.8.8", False),
            ("[::1]", True),
            ("not-an-ip", False),
            (None, False),
            ("", False),
        ],
    )
    def test_is_local_address(self, address: str | None, local: bool) -> None:
        assert is_local_address(address) is local

    def test_in_networks(self) -> None:
        networks = parse_networks(["10.0.0.0/8", "fd00::/8"])
        assert in_networks("10.2.3.4", networks)
        assert in_networks("fd00::1", networks)
        assert not in_networks("11.0.0.1", networks)
        assert not in_networks(None, networks)
        assert not in_networks("garbage", networks)


async def _call(app: Any, scope: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


class TestMiddlewares:
    def test_non_http_scopes_pass_through(self) -> None:
        seen: list[Scope] = []

        async def inner(scope: Scope, receive: Receive, send: Send) -> None:
            seen.append(scope)

        scope = {"type": "lifespan"}
        asyncio.run(_call(ProxyHeadersMiddleware(inner, ["10.0.0.0/8"]), dict(scope)))
        asyncio.run(_call(SecurityHeadersMiddleware(inner), dict(scope)))
        assert all("boomarr.peer" not in s for s in seen)

    def test_proxy_headers(self) -> None:
        seen: list[Scope] = []

        async def inner(scope: Scope, receive: Receive, send: Send) -> None:
            seen.append(scope)

        middleware = ProxyHeadersMiddleware(inner, ["10.0.0.0/8"])
        headers = [
            (b"x-forwarded-for", b"8.8.8.8, 10.0.0.9"),
            (b"x-forwarded-proto", b"gopher"),
        ]
        scope = {
            "type": "http",
            "client": ("10.0.0.1", 1),
            "headers": headers,
            "scheme": "http",
        }
        asyncio.run(_call(middleware, scope))
        assert seen[0]["client"] == ("8.8.8.8", 0)
        assert seen[0]["scheme"] == "http"
        assert seen[0]["boomarr.peer"] == "10.0.0.1"
        # only proxies in the chain: client stays the proxy
        headers = [(b"x-forwarded-for", b"10.0.0.7")]
        asyncio.run(
            _call(
                middleware,
                {"type": "http", "client": ("10.0.0.1", 1), "headers": headers},
            )
        )
        assert seen[1]["client"] == ("10.0.0.1", 1)
        # untrusted peers and missing client info are ignored
        asyncio.run(
            _call(middleware, {"type": "http", "client": None, "headers": headers})
        )
        assert seen[2]["boomarr.peer"] is None

    def test_security_headers_do_not_override(self) -> None:
        async def inner(scope: Scope, receive: Receive, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-security-policy", b"custom")],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        sent = asyncio.run(_call(SecurityHeadersMiddleware(inner), {"type": "http"}))
        headers = dict(sent[0]["headers"])
        assert headers[b"content-security-policy"] == b"custom"
        assert headers[b"x-content-type-options"] == b"nosniff"
        assert sent[1]["type"] == "http.response.body"


class TestSessionManager:
    def test_oidc_state(self) -> None:
        manager = SessionManager("secret", lambda: 1, "")
        assert manager.path == "/"
        token = manager.dump_oidc({"state": "s"})
        assert manager.load_oidc(token) == {"state": "s"}
        assert manager.load_oidc("garbage") is None
        other = SessionManager("other-secret", lambda: 1, "/")
        assert other.load_oidc(token) is None
        list_token = manager._oidc.dumps([1, 2])
        assert manager.load_oidc(list_token) is None

    def test_non_dict_session_is_ignored(self) -> None:
        manager = SessionManager("secret", lambda: 1, "/")

        class FakeRequest:
            def __init__(self) -> None:
                self.cookies = {security.SESSION_COOKIE: manager._serializer.dumps([1])}

        assert manager.read(FakeRequest()) is None  # ty: ignore[invalid-argument-type]


class TestLoginThrottle:
    def test_window_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = [1000.0]
        monkeypatch.setattr(security.time, "monotonic", lambda: now[0])
        throttle = LoginThrottle(max_failures=2, window=60)
        throttle.failure("a")
        throttle.failure("a")
        assert throttle.retry_after("a") == 61
        now[0] += 61
        assert throttle.retry_after("a") == 0
        throttle.failure("a")
        throttle.success("a")
        assert throttle.retry_after("a") == 0
