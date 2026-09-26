"""Tests for OpenID Connect login (client and routes)."""

import time
import urllib.parse
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from boomarr.config import OIDCConfig
from boomarr.const import AuthMethod
from boomarr.daemon import Daemon
from boomarr.web.oidc import OIDCClient, OIDCError, check_access

ISSUER = "https://id.example.com"
KEY = RSAKey.generate_key(2048, parameters={"kid": "k1", "alg": "RS256"}, private=True)
METADATA = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "userinfo_endpoint": f"{ISSUER}/userinfo",
}


def _config(**values: Any) -> OIDCConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "issuer": ISSUER,
        "client_id": "boomarr",
        "client_secret": "s3cret",
    }
    return OIDCConfig(**{**base, **values})


def _id_token(nonce: str, **claims: Any) -> str:
    payload = {
        "iss": ISSUER,
        "aud": "boomarr",
        "exp": int(time.time()) + 300,
        "sub": "user-1",
        "nonce": nonce,
        "preferred_username": "alice",
        "groups": ["media"],
        **claims,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode({"alg": "RS256", "kid": "k1"}, payload, KEY)


@pytest.fixture
def provider() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{ISSUER}/.well-known/openid-configuration").respond(json=METADATA)
        router.get(f"{ISSUER}/jwks").respond(
            json={"keys": [KEY.as_dict(private=False)]}
        )
        router.get(f"{ISSUER}/userinfo").respond(json={"email": "alice@example.com"})
        yield router


def _token_response(router: respx.MockRouter, nonce: str, **claims: Any) -> respx.Route:
    return router.post(f"{ISSUER}/token").respond(
        json={"id_token": _id_token(nonce, **claims), "access_token": "at"}
    )


class TestCheckAccess:
    def test_everyone_allowed_by_default(self) -> None:
        check_access(_config(), "bob", {})

    def test_allowed_users_and_groups(self) -> None:
        config = _config(allowed_users=["Alice"], allowed_groups=["admins"])
        check_access(config, "alice", {})
        check_access(config, "x", {"email": "ALICE"})
        check_access(config, "bob", {"groups": "admins"})
        check_access(config, "bob", {"groups": ["users", "admins"]})
        with pytest.raises(OIDCError, match="not allowed"):
            check_access(config, "bob", {"groups": ["users"]})


class TestClient_:
    def test_login_request(self, provider: respx.MockRouter) -> None:
        import asyncio

        client = OIDCClient()
        request = asyncio.run(client.login_request(_config(), "https://app/cb"))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.url).query)
        assert query["client_id"] == ["boomarr"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["state"] == [request.state]
        assert query["scope"] == ["openid profile email"]
        # metadata is cached
        asyncio.run(client.discover(_config()))
        assert provider.calls.call_count == 1

    def test_authorization_endpoint_with_query(
        self, provider: respx.MockRouter
    ) -> None:
        import asyncio

        provider.get(f"{ISSUER}/.well-known/openid-configuration").respond(
            json={**METADATA, "authorization_endpoint": f"{ISSUER}/auth?tenant=1"}
        )
        request = asyncio.run(OIDCClient().login_request(_config(), "https://app/cb"))
        assert request.url.startswith(f"{ISSUER}/auth?tenant=1&")

    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (httpx.Response(500), "Cannot reach"),
            (httpx.Response(200, text="nope"), "Cannot reach"),
            (httpx.Response(200, json=[1]), "invalid document"),
            (httpx.Response(200, json={"issuer": ISSUER}), "lacks"),
        ],
    )
    def test_discovery_errors(self, response: httpx.Response, message: str) -> None:
        import asyncio

        with respx.mock:
            respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
                return_value=response
            )
            with pytest.raises(OIDCError, match=message):
                asyncio.run(OIDCClient().discover(_config()))

    def _complete(self, config: OIDCConfig | None = None, nonce: str = "n1") -> str:
        import asyncio

        return asyncio.run(
            OIDCClient().complete(
                config or _config(),
                code="code",
                redirect_uri="https://app/cb",
                nonce=nonce,
                verifier="v",
            )
        )

    def test_complete_basic_auth(self, provider: respx.MockRouter) -> None:
        route = _token_response(provider, "n1")
        assert self._complete() == "alice"
        request = route.calls.last.request
        assert request.headers["authorization"].startswith("Basic ")
        assert b"code_verifier=v" in request.content

    def test_complete_client_secret_post_and_userinfo(
        self, provider: respx.MockRouter
    ) -> None:
        provider.get(f"{ISSUER}/.well-known/openid-configuration").respond(
            json={
                **METADATA,
                "token_endpoint_auth_methods_supported": ["client_secret_post"],
            }
        )
        route = _token_response(provider, "n1", preferred_username=None, groups=None)
        config = _config(username_claim="nickname")
        assert self._complete(config) == "alice@example.com"
        assert b"client_secret=s3cret" in route.calls.last.request.content

    def test_complete_public_client(self, provider: respx.MockRouter) -> None:
        route = _token_response(provider, "n1")
        assert self._complete(_config(client_secret=None)) == "alice"
        assert "authorization" not in route.calls.last.request.headers

    def test_userinfo_failures_are_ignored(self, provider: respx.MockRouter) -> None:
        provider.get(f"{ISSUER}/userinfo").respond(500)
        _token_response(provider, "n1", groups=None)
        assert self._complete() == "alice"
        provider.get(f"{ISSUER}/userinfo").mock(side_effect=httpx.ConnectError("down"))
        assert self._complete() == "alice"
        provider.get(f"{ISSUER}/userinfo").respond(json=["x"])
        assert self._complete() == "alice"

    def test_no_userinfo_endpoint(self, provider: respx.MockRouter) -> None:
        metadata = {k: v for k, v in METADATA.items() if k != "userinfo_endpoint"}
        provider.get(f"{ISSUER}/.well-known/openid-configuration").respond(
            json=metadata
        )
        _token_response(provider, "n1", groups=None)
        assert self._complete() == "alice"

    @pytest.mark.parametrize(
        ("setup", "message"),
        [
            (lambda r: r.post(f"{ISSUER}/token").respond(400), "rejected the login"),
            (
                lambda r: r.post(f"{ISSUER}/token").mock(
                    side_effect=httpx.ConnectError("x")
                ),
                "Cannot reach",
            ),
            (
                lambda r: r.post(f"{ISSUER}/token").respond(json={"access_token": "x"}),
                "no ID token",
            ),
            (lambda r: _token_response(r, "other"), "invalid"),
            (
                lambda r: _token_response(r, "n1", aud="someone-else"),
                "another application",
            ),
            (
                lambda r: r.post(f"{ISSUER}/token").respond(
                    json={"id_token": "garbage"}
                ),
                "invalid",
            ),
        ],
    )
    def test_complete_errors(
        self,
        provider: respx.MockRouter,
        setup: Callable[[respx.MockRouter], object],
        message: str,
    ) -> None:
        setup(provider)
        with pytest.raises(OIDCError, match=message):
            self._complete()

    def test_audience_list(self, provider: respx.MockRouter) -> None:
        _token_response(provider, "n1", aud=["other", "boomarr"])
        assert self._complete() == "alice"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _enable_oidc(daemon: Daemon, **values: Any) -> None:
    auth = daemon.config.auth.model_copy(update={"oidc": _config(**values)})
    daemon.config = daemon.config.model_copy(update={"auth": auth})


def _start(
    client: TestClient, next_url: str | None = "/activity"
) -> dict[str, list[str]]:
    params = {"next": next_url} if next_url else {}
    response = client.get(
        "/api/v1/auth/oidc/login", params=params, follow_redirects=False
    )
    assert response.status_code == 303
    return urllib.parse.parse_qs(
        urllib.parse.urlsplit(response.headers["location"]).query
    )


class TestRoutes:
    def test_disabled(self, client: TestClient) -> None:
        assert client.get("/api/v1/auth/oidc/login").status_code == 404
        response = client.get("/api/v1/auth/oidc/callback", follow_redirects=False)
        assert "not%20enabled" in response.headers["location"]

    def test_full_login(
        self, client: TestClient, web_daemon: Daemon, provider: respx.MockRouter
    ) -> None:
        _enable_oidc(web_daemon)
        state = client.get("/api/v1/auth/state").json()
        assert state["oidc"] == {"enabled": True, "name": "SSO", "auto_login": False}
        query = _start(client)
        assert query["redirect_uri"] == ["http://testserver/api/v1/auth/oidc/callback"]
        route = _token_response(provider, query["nonce"][0])
        response = client.get(
            "/api/v1/auth/oidc/callback",
            params={"code": "c", "state": query["state"][0]},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/activity"
        assert route.called
        me = client.get("/api/v1/auth/state").json()["user"]
        assert me == {"name": "alice", "method": "oidc"}
        # the login cookie is single use
        again = client.get(
            "/api/v1/auth/oidc/callback",
            params={"code": "c", "state": query["state"][0]},
            follow_redirects=False,
        )
        assert "expired" in urllib.parse.unquote(again.headers["location"])

    @pytest.mark.parametrize(
        "next_url", [None, "//evil.example", "https://evil", "/a\\b"]
    )
    def test_unsafe_next_is_ignored(
        self,
        client: TestClient,
        web_daemon: Daemon,
        provider: respx.MockRouter,
        next_url: str | None,
    ) -> None:
        _enable_oidc(web_daemon)
        query = _start(client, next_url)
        _token_response(provider, query["nonce"][0])
        response = client.get(
            "/api/v1/auth/oidc/callback",
            params={"code": "c", "state": query["state"][0]},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/"

    def test_state_mismatch_and_provider_error(
        self, client: TestClient, web_daemon: Daemon, provider: respx.MockRouter
    ) -> None:
        _enable_oidc(web_daemon)
        _start(client)
        wrong = client.get(
            "/api/v1/auth/oidc/callback",
            params={"code": "c", "state": "forged"},
            follow_redirects=False,
        )
        assert wrong.headers["location"].startswith("/login?error=")
        denied = client.get(
            "/api/v1/auth/oidc/callback",
            params={"error": "access_denied", "error_description": "User said no"},
            follow_redirects=False,
        )
        assert "User%20said%20no" in denied.headers["location"]

    def test_access_denied_by_group(
        self, client: TestClient, web_daemon: Daemon, provider: respx.MockRouter
    ) -> None:
        _enable_oidc(web_daemon, allowed_groups=["admins"])
        query = _start(client)
        _token_response(provider, query["nonce"][0])
        response = client.get(
            "/api/v1/auth/oidc/callback",
            params={"code": "c", "state": query["state"][0]},
            follow_redirects=False,
        )
        assert "not%20allowed" in response.headers["location"]
        assert client.get("/api/v1/auth/state").json()["user"] is None

    def test_discovery_failure_redirects_to_login(
        self, client: TestClient, web_daemon: Daemon
    ) -> None:
        _enable_oidc(web_daemon)
        with respx.mock:
            respx.get(f"{ISSUER}/.well-known/openid-configuration").respond(503)
            response = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
        assert response.headers["location"].startswith("/login?error=Cannot")

    def test_not_offered_for_external_auth(
        self, client: TestClient, web_daemon: Daemon
    ) -> None:
        _enable_oidc(web_daemon)
        auth = web_daemon.config.auth.model_copy(update={"method": AuthMethod.EXTERNAL})
        web_daemon.config = web_daemon.config.model_copy(update={"auth": auth})
        assert client.get("/api/v1/auth/state").json()["oidc"]["enabled"] is False
