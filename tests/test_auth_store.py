"""Tests for boomarr.auth_store."""

import json
import stat
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from boomarr import auth_store as auth_module
from boomarr.auth_store import AuthStore, CredentialsError


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "auth.json"


class TestAuthStore:
    def test_new_store_has_setup_token_and_keys(self, path: Path) -> None:
        store = AuthStore(path)
        assert not store.has_credentials
        assert store.username is None
        assert store.setup_token and len(store.setup_token) == 16
        assert len(store.api_key) == 32
        assert store.session_version == 1
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert store.snapshot() == {"username": None, "has_credentials": False}

    def test_state_survives_restart(self, path: Path) -> None:
        store = AuthStore(path)
        store.set_credentials(" admin ", "password1")
        again = AuthStore(path)
        assert again.username == "admin"
        assert again.api_key == store.api_key
        assert again.session_secret == store.session_secret
        assert again.setup_token is None
        assert again.verify("admin", "password1")

    def test_setup_token_dropped_when_credentials_exist(self, path: Path) -> None:
        store = AuthStore(path)
        store.set_credentials("admin", "password1")
        data = json.loads(path.read_text())
        data["setup_token"] = "stale"
        path.write_text(json.dumps(data))
        assert AuthStore(path).setup_token is None
        assert json.loads(path.read_text())["setup_token"] is None

    @pytest.mark.parametrize(
        ("username", "password", "message"),
        [(" ", "password1", "Username"), ("admin", "short", "at least 8")],
    )
    def test_invalid_credentials(
        self, path: Path, username: str, password: str, message: str
    ) -> None:
        with pytest.raises(CredentialsError, match=message):
            AuthStore(path).set_credentials(username, password)

    def test_verify(self, path: Path) -> None:
        store = AuthStore(path)
        assert not store.verify("admin", "password1")  # no account yet
        store.set_credentials("admin", "password1")
        assert store.verify("admin", "password1")
        assert not store.verify("admin", "wrong-password")
        assert not store.verify("other", "password1")

    def test_verify_rehashes_outdated_hash(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = AuthStore(path)
        store.set_credentials("admin", "password1")
        old_hash = json.loads(path.read_text())["password_hash"]

        class AlwaysRehash(PasswordHasher):
            def check_needs_rehash(self, hash: str | bytes) -> bool:
                return True

        monkeypatch.setattr(auth_module, "_HASHER", AlwaysRehash())
        assert store.verify("admin", "password1")
        assert json.loads(path.read_text())["password_hash"] != old_hash

    def test_verify_invalid_stored_hash(self, path: Path) -> None:
        store = AuthStore(path)
        store.set_credentials("admin", "password1")
        store._state.password_hash = "not-a-hash"
        assert not store.verify("admin", "password1")

    def test_change_password(self, path: Path) -> None:
        store = AuthStore(path)
        with pytest.raises(CredentialsError):
            store.change_password("x", "password2")
        store.set_credentials("admin", "password1")
        version = store.session_version
        with pytest.raises(CredentialsError, match="not correct"):
            store.change_password("wrong", "password2")
        store.change_password("password1", "password2")
        assert store.verify("admin", "password2")
        assert store.session_version == version + 1

    def test_regenerate_and_revoke(self, path: Path) -> None:
        store = AuthStore(path)
        key = store.api_key
        assert store.regenerate_api_key() != key
        version = store.session_version
        store.revoke_sessions()
        assert store.session_version == version + 1

    def test_secret_key_from_env(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOMARR_SECRET_KEY", "from-env")
        assert AuthStore(path).session_secret == "from-env"

    def test_bootstrap_from_env(
        self, path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = AuthStore(path)
        store.bootstrap_from_env()  # nothing set
        assert not store.has_credentials
        monkeypatch.setenv("BOOMARR_USERNAME", "admin")
        monkeypatch.setenv("BOOMARR_PASSWORD", "password1")
        store.bootstrap_from_env()
        assert store.verify("admin", "password1")
        version = store.session_version
        store.bootstrap_from_env()  # unchanged: sessions stay valid
        assert store.session_version == version
        monkeypatch.setenv("BOOMARR_PASSWORD", "password2")
        store.bootstrap_from_env()
        assert store.verify("admin", "password2")

    @pytest.mark.parametrize("content", ["{broken", "[1, 2]"])
    def test_corrupt_file(self, path: Path, content: str) -> None:
        path.write_text(content)
        store = AuthStore(path)
        assert not store.has_credentials
        assert json.loads(path.read_text())["api_key"] == store.api_key

    def test_unknown_keys_ignored(self, path: Path) -> None:
        path.write_text(json.dumps({"username": "a", "future": 1}))
        assert AuthStore(path).username == "a"

    def test_unwritable_directory(
        self,
        path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail(*_: object, **__: object) -> None:
            raise OSError("read-only")

        monkeypatch.setattr(auth_module.tempfile, "mkstemp", fail)
        store = AuthStore(path)
        store.set_credentials("admin", "password1")
        assert store.verify("admin", "password1")
        assert "only live until the next restart" in caplog.text
