"""OpenID Connect login (authorization code flow with PKCE).

Works with any standards compliant provider (Authentik, Authelia, Keycloak,
Pocket ID, Zitadel, Google, ...). The ID token is verified against the
provider's JWKS (signature, issuer, audience, expiry and nonce).
"""

import base64
import hashlib
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from boomarr.config import OIDCConfig

_DISCOVERY_TTL = 3600.0


class OIDCError(Exception):
    """Login failed; the message is safe to show to the user."""


@dataclass
class OIDCLoginRequest:
    """What has to be remembered between the redirect and the callback."""

    url: str
    state: str
    nonce: str
    verifier: str


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class OIDCClient:
    """Stateless helper around one provider configuration."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=10.0)

    async def _get_json(self, url: str) -> dict[str, Any]:
        cached = self._cache.get(url)
        if cached and time.monotonic() - cached[0] < _DISCOVERY_TTL:
            return cached[1]
        try:
            async with self._client() as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError(f"Cannot reach the identity provider: {exc}") from exc
        if not isinstance(data, dict):
            raise OIDCError("The identity provider returned an invalid document")
        self._cache[url] = (time.monotonic(), data)
        return data

    async def discover(self, config: OIDCConfig) -> dict[str, Any]:
        """Fetch (and cache) the provider metadata."""
        metadata = await self._get_json(config.discovery_url)
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
            if key not in metadata:
                raise OIDCError(f"The provider metadata lacks '{key}'")
        return metadata

    async def login_request(
        self, config: OIDCConfig, redirect_uri: str
    ) -> OIDCLoginRequest:
        metadata = await self.discover(config)
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier, challenge = _pkce_pair()
        params = {
            "response_type": "code",
            "client_id": config.client_id or "",
            "redirect_uri": redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        separator = "&" if "?" in metadata["authorization_endpoint"] else "?"
        url = f"{metadata['authorization_endpoint']}{separator}{urllib.parse.urlencode(params)}"
        return OIDCLoginRequest(url=url, state=state, nonce=nonce, verifier=verifier)

    async def _exchange(
        self,
        config: OIDCConfig,
        metadata: dict[str, Any],
        code: str,
        redirect_uri: str,
        verifier: str,
    ) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": config.client_id or "",
        }
        auth: httpx.BasicAuth | None = None
        secret = (
            config.client_secret.get_secret_value() if config.client_secret else None
        )
        methods = metadata.get("token_endpoint_auth_methods_supported") or [
            "client_secret_basic"
        ]
        if secret and "client_secret_basic" in methods:
            auth = httpx.BasicAuth(config.client_id or "", secret)
        elif secret:
            data["client_secret"] = secret
        try:
            async with self._client() as client:
                response = await client.post(
                    metadata["token_endpoint"],
                    data=data,
                    auth=auth or httpx.USE_CLIENT_DEFAULT,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise OIDCError(f"Cannot reach the identity provider: {exc}") from exc
        if response.status_code != 200:
            raise OIDCError(
                f"The identity provider rejected the login ({response.status_code})"
            )
        tokens = response.json()
        if not isinstance(tokens, dict) or "id_token" not in tokens:
            raise OIDCError("The identity provider returned no ID token")
        return tokens

    async def _claims(
        self, config: OIDCConfig, metadata: dict[str, Any], id_token: str, nonce: str
    ) -> dict[str, Any]:
        jwks = await self._get_json(metadata["jwks_uri"])
        try:
            key_set = KeySet.import_key_set(jwks)  # ty: ignore[invalid-argument-type]
            token = jwt.decode(id_token, key_set)
            registry = jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": metadata["issuer"]},
                exp={"essential": True},
                nonce={"essential": True, "value": nonce},
            )
            registry.validate(token.claims)
        except (JoseError, ValueError) as exc:
            raise OIDCError(f"The ID token is invalid: {exc}") from exc
        claims = dict(token.claims)
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if config.client_id not in audiences:
            raise OIDCError("The ID token was issued for another application")
        return claims

    async def _userinfo(
        self, metadata: dict[str, Any], access_token: str | None
    ) -> dict[str, Any]:
        endpoint = metadata.get("userinfo_endpoint")
        if not endpoint or not access_token:
            return {}
        try:
            async with self._client() as client:
                response = await client.get(
                    endpoint, headers={"Authorization": f"Bearer {access_token}"}
                )
                data = response.json() if response.status_code == 200 else {}
        except httpx.HTTPError, ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def complete(
        self,
        config: OIDCConfig,
        *,
        code: str,
        redirect_uri: str,
        nonce: str,
        verifier: str,
    ) -> str:
        """Finish the login and return the username (raises :class:`OIDCError`)."""
        metadata = await self.discover(config)
        tokens = await self._exchange(config, metadata, code, redirect_uri, verifier)
        claims = await self._claims(config, metadata, tokens["id_token"], nonce)
        if config.groups_claim not in claims or config.username_claim not in claims:
            claims = {
                **await self._userinfo(metadata, tokens.get("access_token")),
                **claims,
            }
        username = str(
            claims.get(config.username_claim)
            or claims.get("email")
            or claims.get("sub")
        )
        check_access(config, username, claims)
        return username


def check_access(config: OIDCConfig, username: str, claims: dict[str, Any]) -> None:
    """Enforce ``allowed_users`` / ``allowed_groups`` (empty = everyone)."""
    if not config.allowed_users and not config.allowed_groups:
        return
    identities = {username.lower(), str(claims.get("email", "")).lower()}
    if any(user.lower() in identities for user in config.allowed_users):
        return
    groups = claims.get(config.groups_claim) or []
    if isinstance(groups, str):
        groups = [groups]
    if set(config.allowed_groups) & {str(g) for g in groups}:
        return
    raise OIDCError(f"'{username}' is not allowed to use Boomarr")
