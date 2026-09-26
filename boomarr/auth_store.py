"""Persistent authentication state (credentials and generated secrets).

Stored in ``auth.json`` next to the configuration with ``0600``
permissions, separate from ``boomarr.yml`` (which is meant to be edited and
shared) and from the probe cache (which may be deleted at any time).
"""

import contextlib
import json
import logging
import os
import secrets
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from boomarr.const import ENV_ADMIN_PASSWORD, ENV_ADMIN_USERNAME, ENV_SECRET_KEY

_LOGGER = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
_HASHER = PasswordHasher()
# Verified against when the username is wrong so that response times do not
# reveal whether a user exists.
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))


class CredentialsError(ValueError):
    """Invalid username/password input (too short, wrong current password...)."""


@dataclass
class AuthState:
    """Everything persisted in ``auth.json``."""

    username: str | None = None
    password_hash: str | None = None
    session_version: int = 1
    api_key: str = field(default_factory=lambda: secrets.token_hex(16))
    session_secret: str = field(default_factory=lambda: secrets.token_urlsafe(48))
    setup_token: str | None = field(default_factory=lambda: secrets.token_hex(8))


class AuthStore:
    """Thread-safe access to :class:`AuthState` with atomic persistence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._state = self._read()
        if self._state.username and self._state.setup_token:
            self._state.setup_token = None
        self._persist()

    # -- persistence ------------------------------------------------------

    def _read(self) -> AuthState:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AuthState()
        except (OSError, ValueError) as exc:
            _LOGGER.error(
                "Cannot read '%s' (%s); starting with a new one", self.path, exc
            )
            return AuthState()
        if not isinstance(data, dict):
            return AuthState()
        known = AuthState.__dataclass_fields__
        return AuthState(**{k: v for k, v in data.items() if k in known})

    def _persist(self) -> None:
        payload = json.dumps(asdict(self._state), indent=2)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".auth.")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError as exc:
            _LOGGER.warning(
                "Cannot write '%s' (%s): credentials and generated keys only "
                "live until the next restart",
                self.path,
                exc,
            )

    # -- read access ------------------------------------------------------

    @property
    def has_credentials(self) -> bool:
        return bool(self._state.username and self._state.password_hash)

    @property
    def username(self) -> str | None:
        return self._state.username

    @property
    def api_key(self) -> str:
        return self._state.api_key

    @property
    def session_version(self) -> int:
        return self._state.session_version

    @property
    def setup_token(self) -> str | None:
        return None if self.has_credentials else self._state.setup_token

    @property
    def session_secret(self) -> str:
        return os.environ.get(ENV_SECRET_KEY) or self._state.session_secret

    def snapshot(self) -> dict[str, Any]:
        """Non-secret information for diagnostics."""
        return {"username": self.username, "has_credentials": self.has_credentials}

    # -- mutations --------------------------------------------------------

    @staticmethod
    def _check_new(username: str, password: str) -> str:
        username = username.strip()
        if not username:
            raise CredentialsError("Username must not be empty")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise CredentialsError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
            )
        return username

    def set_credentials(self, username: str, password: str) -> None:
        """Set the admin account and invalidate all existing sessions."""
        username = self._check_new(username, password)
        with self._lock:
            self._state.username = username
            self._state.password_hash = _HASHER.hash(password)
            self._state.session_version += 1
            self._state.setup_token = None
            self._persist()

    def verify(self, username: str, password: str) -> bool:
        """Check a login attempt (constant time regarding the username)."""
        state = self._state
        stored = state.password_hash if state.username == username.strip() else None
        if stored is None:
            # Spend the same time as for a real user, then fail.
            with contextlib.suppress(VerifyMismatchError):
                _HASHER.verify(_DUMMY_HASH, password)
            return False
        try:
            _HASHER.verify(stored, password)
        except VerifyMismatchError, VerificationError, InvalidHashError:
            return False
        if _HASHER.check_needs_rehash(stored):
            with self._lock:
                self._state.password_hash = _HASHER.hash(password)
                self._persist()
        return True

    def change_password(self, current: str, new: str) -> None:
        if not self.username or not self.verify(self.username, current):
            raise CredentialsError("The current password is not correct")
        self.set_credentials(self.username, new)

    def regenerate_api_key(self) -> str:
        with self._lock:
            self._state.api_key = secrets.token_hex(16)
            self._persist()
            return self._state.api_key

    def revoke_sessions(self) -> None:
        with self._lock:
            self._state.session_version += 1
            self._persist()

    def bootstrap_from_env(self) -> None:
        """Apply ``BOOMARR_USERNAME``/``BOOMARR_PASSWORD`` (e.g. from a k8s Secret)."""
        username = os.environ.get(ENV_ADMIN_USERNAME)
        password = os.environ.get(ENV_ADMIN_PASSWORD)
        if not username or not password:
            return
        if self.username == username.strip() and self.verify(username, password):
            return
        self.set_credentials(username, password)
        _LOGGER.info("Admin account '%s' set from environment variables", username)
