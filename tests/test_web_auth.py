"""Tests for authentication: sessions, setup, login, API key, CSRF."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from boomarr.auth_store import AuthStore
from boomarr.const import AuthMethod
from boomarr.daemon import Daemon
from boomarr.web.security import SESSION_COOKIE
from tests.conftest import CSRF, LOCAL_CLIENT


def _set_auth(daemon: Daemon, **values: object) -> None:
    auth = daemon.config.auth.model_copy(update=values)
    daemon.config = daemon.config.model_copy(update={"auth": auth})


def _set_server(daemon: Daemon, **values: object) -> None:
    server = daemon.config.server.model_copy(update=values)
    daemon.config = daemon.config.model_copy(update={"server": server})


class TestState:
    def test_setup_required(self, client: TestClient) -> None:
        state = client.get("/api/v1/auth/state").json()
        assert state == {
            "method": "forms",
            "setup_required": True,
            "setup_token_required": True,
            "password_login": True,
            "oidc": {"enabled": False, "name": "SSO", "auto_login": False},
            "user": None,
        }

    def test_logged_in(self, admin: TestClient) -> None:
        state = admin.get("/api/v1/auth/state").json()
        assert state["user"] == {"name": "admin", "method": "session"}
        assert state["setup_required"] is False

    def test_protected_endpoints_need_login(self, client: TestClient) -> None:
        assert client.get("/api/v1/dashboard").status_code == 401
        assert client.post("/api/v1/scan").status_code == 401


class TestSetup:
    def test_setup_with_token(self, client: TestClient, auth: AuthStore) -> None:
        body = {"username": "admin", "password": "password1", "token": "wrong"}
        assert client.post("/api/v1/auth/setup", json=body).status_code == 403
        body["token"] = auth.setup_token or ""
        response = client.post("/api/v1/auth/setup", json=body)
        assert response.status_code == 204
        assert SESSION_COOKIE in response.cookies
        assert client.get("/api/v1/auth/state").json()["user"]["name"] == "admin"
        assert client.post("/api/v1/auth/setup", json=body).status_code == 409

    def test_setup_from_local_network_needs_no_token(
        self, make_client: Callable[..., TestClient]
    ) -> None:
        client = make_client(LOCAL_CLIENT)
        assert client.get("/api/v1/auth/state").json()["setup_token_required"] is False
        response = client.post(
            "/api/v1/auth/setup", json={"username": "admin", "password": "short"}
        )
        assert response.status_code == 422
        assert "at least 8" in response.json()["detail"]

    def test_setup_not_available_for_other_methods(
        self, client: TestClient, web_daemon: Daemon
    ) -> None:
        _set_auth(web_daemon, method=AuthMethod.NONE)
        body = {"username": "admin", "password": "password1"}
        assert client.post("/api/v1/auth/setup", json=body).status_code == 409


class TestLogin:
    def test_login_logout(self, admin: TestClient) -> None:
        assert admin.get("/api/v1/dashboard").status_code == 200
        assert admin.post("/api/v1/auth/logout").status_code == 204
        assert admin.get("/api/v1/dashboard").status_code == 401

    def test_session_cookie_without_remember(
        self, client: TestClient, auth: AuthStore
    ) -> None:
        auth.set_credentials("admin", "password1")
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1", "remember": False},
        )
        assert "Max-Age" not in response.headers["set-cookie"]

    def test_wrong_password_and_throttle(
        self, client: TestClient, auth: AuthStore
    ) -> None:
        auth.set_credentials("admin", "password1")
        body = {"username": "admin", "password": "wrong"}
        for _ in range(5):
            assert client.post("/api/v1/auth/login", json=body).status_code == 401
        response = client.post("/api/v1/auth/login", json=body)
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0

    def test_password_login_disabled(
        self, client: TestClient, web_daemon: Daemon
    ) -> None:
        oidc = web_daemon.config.auth.oidc.model_copy(
            update={
                "enabled": True,
                "issuer": "https://id.example.com",
                "client_id": "boomarr",
                "disable_password_login": True,
            }
        )
        _set_auth(web_daemon, oidc=oidc)
        body = {"username": "admin", "password": "password1"}
        assert client.post("/api/v1/auth/login", json=body).status_code == 403

    def test_invalid_body(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/login", json={"username": ""})
        assert response.status_code == 422
        assert response.json()["errors"][0]["loc"][0] == "body"

    def test_sessions_revoked_by_password_change(
        self, admin: TestClient, make_client: Callable[..., TestClient]
    ) -> None:
        other = make_client()
        other.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "password1"}
        )
        response = admin.post(
            "/api/v1/auth/password", json={"current": "password1", "new": "password2"}
        )
        assert response.status_code == 204
        assert admin.get("/api/v1/dashboard").status_code == 200  # got a new cookie
        assert other.get("/api/v1/dashboard").status_code == 401

    def test_password_change_errors(
        self, admin: TestClient, web_daemon: Daemon
    ) -> None:
        response = admin.post(
            "/api/v1/auth/password", json={"current": "nope", "new": "password2"}
        )
        assert response.status_code == 422
        _set_auth(web_daemon, method=AuthMethod.NONE)
        response = admin.post(
            "/api/v1/auth/password", json={"current": "password1", "new": "password2"}
        )
        assert response.status_code == 409

    def test_password_change_with_api_key_keeps_no_cookie(
        self, client: TestClient, auth: AuthStore
    ) -> None:
        auth.set_credentials("admin", "password1")
        response = client.post(
            "/api/v1/auth/password",
            json={"current": "password1", "new": "password2"},
            headers={"X-Api-Key": auth.api_key},
        )
        assert response.status_code == 204
        assert SESSION_COOKIE not in response.cookies

    def test_revoke_sessions(self, admin: TestClient) -> None:
        assert admin.post("/api/v1/auth/sessions/revoke").status_code == 204
        assert admin.get("/api/v1/dashboard").status_code == 401

    def test_tampered_cookie(self, admin: TestClient) -> None:
        admin.cookies.set(SESSION_COOKIE, "garbage")
        assert admin.get("/api/v1/dashboard").status_code == 401


class TestCsrf:
    def test_cookie_requests_need_header(self, admin: TestClient) -> None:
        del admin.headers["X-Requested-With"]
        response = admin.post("/api/v1/scans", json={})
        assert response.status_code == 403
        assert admin.get("/api/v1/dashboard").status_code == 200
        assert admin.post("/api/v1/scans", json={}, headers=CSRF).status_code == 202


class TestApiKey:
    @pytest.mark.parametrize(
        "how",
        ["header", "query", "bearer", "basic"],
    )
    def test_api_key_variants(
        self, client: TestClient, auth: AuthStore, how: str
    ) -> None:
        import base64

        key = auth.api_key
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if how == "header":
            headers["X-Api-Key"] = key
        elif how == "query":
            params["apikey"] = key
        elif how == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        else:
            token = base64.b64encode(f"sonarr:{key}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        response = client.post("/api/v1/webhook/sonarr", headers=headers, params=params)
        assert response.status_code == 202

    def test_wrong_key_is_rejected_even_with_session(self, admin: TestClient) -> None:
        response = admin.get("/api/v1/dashboard", headers={"X-Api-Key": "wrong"})
        assert response.status_code == 401

    @pytest.mark.parametrize("value", ["Basic !!!", "Basic " + "dXNlcg==", "Digest x"])
    def test_malformed_authorization(self, client: TestClient, value: str) -> None:
        response = client.get("/api/v1/dashboard", headers={"Authorization": value})
        assert response.status_code == 401

    def test_show_and_regenerate(self, admin: TestClient, auth: AuthStore) -> None:
        data = admin.get("/api/v1/auth/apikey").json()
        assert data == {"api_key": auth.api_key, "source": "generated"}
        new = admin.post("/api/v1/auth/apikey/regenerate").json()
        assert new["api_key"] != data["api_key"]

    def test_configured_key(self, admin: TestClient, web_daemon: Daemon) -> None:
        from pydantic import SecretStr

        _set_server(web_daemon, api_key=SecretStr("configured"))
        headers = {"X-Api-Key": "configured"}
        assert admin.get("/api/v1/auth/apikey", headers=headers).json() == {
            "api_key": "configured",
            "source": "config",
        }
        assert admin.post("/api/v1/auth/apikey/regenerate").status_code == 409
        web_daemon.config._env_overrides.add("server.api_key")
        assert admin.get("/api/v1/auth/apikey").json()["source"] == "environment"

    def test_env_key(self, admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEBHOOK_API_KEY", "legacy-env")
        data = admin.get("/api/v1/auth/apikey").json()
        assert data == {"api_key": "legacy-env", "source": "environment"}
        response = admin.post("/api/v1/auth/apikey/regenerate")
        assert response.status_code == 409


class TestOtherMethods:
    def test_method_none(self, client: TestClient, web_daemon: Daemon) -> None:
        _set_auth(web_daemon, method=AuthMethod.NONE)
        assert client.get("/api/v1/dashboard").status_code == 200
        assert (
            client.post("/api/v1/scans").status_code == 202
        )  # no cookie: no CSRF check

    def test_local_bypass(
        self, make_client: Callable[..., TestClient], web_daemon: Daemon
    ) -> None:
        _set_auth(web_daemon, local_bypass=True)
        assert make_client(LOCAL_CLIENT).get("/api/v1/dashboard").status_code == 200
        assert make_client().get("/api/v1/dashboard").status_code == 401

    def test_external(
        self, make_client: Callable[..., TestClient], web_daemon: Daemon
    ) -> None:
        _set_auth(web_daemon, method=AuthMethod.EXTERNAL)
        _set_server(web_daemon, trusted_proxies=["192.168.0.0/16"])
        headers = {"Remote-User": "alice", "X-Forwarded-For": "93.184.216.40"}
        proxied = make_client(LOCAL_CLIENT)
        state = proxied.get("/api/v1/auth/state", headers=headers).json()
        assert state["user"] == {"name": "alice", "method": "external"}
        direct = make_client()
        assert direct.get("/api/v1/dashboard", headers=headers).status_code == 401
        assert proxied.get("/api/v1/dashboard").status_code == 401
