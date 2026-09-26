"""Login, logout, first-run setup, OIDC and API key management."""

import logging
import os
import secrets
import urllib.parse
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from boomarr.auth_store import CredentialsError
from boomarr.const import ENV_API_KEY, ENV_WEBHOOK_API_KEY, AuthMethod
from boomarr.web.oidc import OIDCClient, OIDCError
from boomarr.web.security import (
    LoginThrottle,
    Principal,
    SessionManager,
    client_host,
    effective_api_key,
    is_local_address,
    require_user,
    resolve_principal,
)

if TYPE_CHECKING:  # pragma: no cover
    from boomarr.daemon import Daemon

_LOGGER = logging.getLogger(__name__)
_OIDC_COOKIE = "boomarr_oidc"

router = APIRouter(tags=["auth"])
User = Annotated[Principal, Depends(require_user)]


def _daemon(request: Request) -> Daemon:
    return request.app.state.daemon


def _sessions(request: Request) -> SessionManager:
    return request.app.state.sessions


def _password_login_allowed(daemon: Daemon) -> bool:
    auth = daemon.config.auth
    return auth.method == AuthMethod.FORMS and not (
        auth.oidc.enabled and auth.oidc.disable_password_login
    )


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = True


class Setup(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    token: str = ""


class PasswordChange(BaseModel):
    current: str = Field(max_length=1024)
    new: str = Field(min_length=1, max_length=1024)


@router.get("/state")
async def auth_state(request: Request) -> dict[str, Any]:
    """Public: what the login page needs to know."""
    daemon = _daemon(request)
    auth = daemon.config.auth
    principal = resolve_principal(request)
    setup_required = auth.method == AuthMethod.FORMS and not daemon.auth.has_credentials
    return {
        "method": auth.method.value,
        "setup_required": setup_required,
        "setup_token_required": setup_required
        and not is_local_address(client_host(request)),
        "password_login": _password_login_allowed(daemon),
        "oidc": {
            "enabled": auth.oidc.enabled and auth.method == AuthMethod.FORMS,
            "name": auth.oidc.name,
            "auto_login": auth.oidc.auto_login,
        },
        "user": (
            {"name": principal.name, "method": principal.method} if principal else None
        ),
    }


@router.post("/setup", status_code=status.HTTP_204_NO_CONTENT)
async def setup(body: Setup, request: Request) -> Response:
    """Create the admin account on first start."""
    daemon = _daemon(request)
    if daemon.config.auth.method != AuthMethod.FORMS or daemon.auth.has_credentials:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already complete")
    expected = daemon.auth.setup_token or ""
    if not is_local_address(client_host(request)) and not secrets.compare_digest(
        body.token.strip(), expected
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The setup token is not correct")
    try:
        daemon.auth.set_credentials(body.username, body.password)
    except CredentialsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    _LOGGER.info("Admin account '%s' created", daemon.auth.username)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _sessions(request).issue(
        response,
        request,
        {"u": daemon.auth.username, "m": "session", "v": daemon.auth.session_version},
    )
    return response


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(body: Credentials, request: Request) -> Response:
    daemon = _daemon(request)
    if not _password_login_allowed(daemon):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password login is disabled")
    throttle: LoginThrottle = request.app.state.throttle
    key = client_host(request) or "unknown"
    if wait := throttle.retry_after(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed logins, try again in {wait} seconds",
            headers={"Retry-After": str(wait)},
        )
    if not daemon.auth.verify(body.username, body.password):
        throttle.failure(key)
        _LOGGER.warning("Failed login for '%s' from %s", body.username, key)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid username or password"
        )
    throttle.success(key)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _sessions(request).issue(
        response,
        request,
        {"u": daemon.auth.username, "m": "session", "v": daemon.auth.session_version},
        persistent=body.remember,
    )
    _LOGGER.info("'%s' logged in from %s", daemon.auth.username, key)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _sessions(request).clear(response)
    return response


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange, request: Request, user: User
) -> Response:
    daemon = _daemon(request)
    if daemon.config.auth.method != AuthMethod.FORMS or not daemon.auth.has_credentials:
        raise HTTPException(status.HTTP_409_CONFLICT, "No local account to change")
    try:
        daemon.auth.change_password(body.current, body.new)
    except CredentialsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    _LOGGER.info(
        "Password changed by '%s'; all other sessions were signed out", user.name
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if user.uses_cookie:
        _sessions(request).issue(
            response,
            request,
            {
                "u": daemon.auth.username,
                "m": user.method,
                "v": daemon.auth.session_version,
            },
        )
    return response


@router.post("/sessions/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_sessions(request: Request, user: User) -> Response:
    daemon = _daemon(request)
    daemon.auth.revoke_sessions()
    _LOGGER.info("All sessions revoked by '%s'", user.name)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _sessions(request).clear(response)
    return response


def _api_key_source(daemon: Daemon) -> str:
    if daemon.config.server.api_key is not None:
        env = "server.api_key" in daemon.config._env_overrides
        return "environment" if env else "config"
    if os.environ.get(ENV_API_KEY) or os.environ.get(ENV_WEBHOOK_API_KEY):
        return "environment"
    return "generated"


@router.get("/apikey")
async def get_api_key(request: Request, _: User) -> dict[str, Any]:
    daemon = _daemon(request)
    return {"api_key": effective_api_key(daemon), "source": _api_key_source(daemon)}


@router.post("/apikey/regenerate")
async def regenerate_api_key(request: Request, user: User) -> dict[str, Any]:
    daemon = _daemon(request)
    source = _api_key_source(daemon)
    if source != "generated":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The API key is set in the {source}; change it there",
        )
    daemon.auth.regenerate_api_key()
    _LOGGER.info("API key regenerated by '%s'", user.name)
    return {"api_key": effective_api_key(daemon), "source": source}


# ---------------------------------------------------------------------------
# OpenID Connect
# ---------------------------------------------------------------------------


def _redirect_uri(request: Request) -> str:
    base = f"{request.url.scheme}://{request.url.netloc}"
    url_base = _daemon(request).config.server.url_base
    return f"{base}{url_base}/api/v1/auth/oidc/callback"


def _safe_next(value: str | None, url_base: str) -> str:
    """Only allow local, absolute paths as post-login redirect targets."""
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return f"{url_base}/"
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc:  # pragma: no cover - excluded above
        return f"{url_base}/"
    return value


def _oidc_enabled(daemon: Daemon) -> bool:
    auth = daemon.config.auth
    return auth.method == AuthMethod.FORMS and auth.oidc.enabled


@router.get("/oidc/login", include_in_schema=False)
async def oidc_login(request: Request, next: str | None = None) -> RedirectResponse:
    daemon = _daemon(request)
    url_base = daemon.config.server.url_base
    if not _oidc_enabled(daemon):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Single sign-on is not enabled")
    client: OIDCClient = request.app.state.oidc
    try:
        login_request = await client.login_request(
            daemon.config.auth.oidc, _redirect_uri(request)
        )
    except OIDCError as exc:
        _LOGGER.error("OIDC login failed: %s", exc)
        return RedirectResponse(
            f"{url_base}/login?error={urllib.parse.quote(str(exc))}", status_code=303
        )
    response = RedirectResponse(login_request.url, status_code=303)
    response.set_cookie(
        _OIDC_COOKIE,
        _sessions(request).dump_oidc(
            {
                "state": login_request.state,
                "nonce": login_request.nonce,
                "verifier": login_request.verifier,
                "next": _safe_next(next, url_base),
            }
        ),
        max_age=600,
        path=_sessions(request).path,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/oidc/callback", include_in_schema=False)
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    daemon = _daemon(request)
    url_base = daemon.config.server.url_base
    sessions = _sessions(request)

    def fail(message: str) -> RedirectResponse:
        _LOGGER.warning("OIDC login failed: %s", message)
        response = RedirectResponse(
            f"{url_base}/login?error={urllib.parse.quote(message)}", status_code=303
        )
        response.delete_cookie(_OIDC_COOKIE, path=sessions.path)
        return response

    if not _oidc_enabled(daemon):
        return fail("Single sign-on is not enabled")
    if error:
        return fail(error_description or error)
    stored = sessions.load_oidc(request.cookies.get(_OIDC_COOKIE, ""))
    if (
        not stored
        or not code
        or not state
        or not secrets.compare_digest(state, str(stored.get("state", "")))
    ):
        return fail("The login request expired or is invalid, please try again")
    client: OIDCClient = request.app.state.oidc
    try:
        username = await client.complete(
            daemon.config.auth.oidc,
            code=code,
            redirect_uri=_redirect_uri(request),
            nonce=str(stored["nonce"]),
            verifier=str(stored["verifier"]),
        )
    except OIDCError as exc:
        return fail(str(exc))
    response = RedirectResponse(
        str(stored.get("next") or f"{url_base}/"), status_code=303
    )
    response.delete_cookie(_OIDC_COOKIE, path=sessions.path)
    sessions.issue(
        response,
        request,
        {"u": username, "m": "oidc", "v": daemon.auth.session_version},
    )
    _LOGGER.info("'%s' logged in via %s", username, daemon.config.auth.oidc.name)
    return response
