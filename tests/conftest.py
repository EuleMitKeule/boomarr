"""Pytest configuration and shared fixtures.

Provides common test fixtures, configuration, and utilities for the test suite.
Includes setup/teardown logic and mock objects used across multiple test modules.
"""

import asyncio
import logging
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boomarr import config as config_module
from boomarr.auth_store import AuthStore
from boomarr.config_store import ConfigStore
from boomarr.daemon import Daemon
from boomarr.web.app import create_app
from tests.fixtures import MEDIA_DIR


@pytest.fixture(autouse=True)
def reset_config() -> Iterator[None]:
    """Reset the global config singleton before every test."""
    config_module._config = None
    yield
    config_module._config = None


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """Undo ``setup_logging`` side effects (handlers, propagate) after a test."""
    logger = logging.getLogger("boomarr")
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = True
    logger.setLevel(logging.NOTSET)


@pytest.fixture
def fixtures_media_dir() -> Path:
    """Root of the committed fixture media files."""
    return MEDIA_DIR


_ENV_VARS = (
    "BOOMARR_API_KEY",
    "WEBHOOK_API_KEY",
    "BOOMARR_USERNAME",
    "BOOMARR_PASSWORD",
    "BOOMARR_SECRET_KEY",
    "BOOMARR_NOTIFY_URLS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep variables of the developer's shell out of the tests."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


LIBRARY_YAML = """\
output_path: {out}
triggers: []
libraries:
  - name: Movies
    input_path: {movies}
    symlink_libraries:
      - filters:
          - type: audio_language
            languages: [deu]
"""


@pytest.fixture
def movies_dir(tmp_path: Path) -> Path:
    """A private copy of the fixture movies."""
    target = tmp_path / "media" / "movies"
    shutil.copytree(MEDIA_DIR / "movies", target)
    return target


@pytest.fixture
def config_dir(tmp_path: Path, movies_dir: Path) -> Path:
    """A config directory with one library (``Movies`` → German audio)."""
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "boomarr.yml").write_text(
        LIBRARY_YAML.format(out=tmp_path / "out", movies=movies_dir), encoding="utf-8"
    )
    return directory


@pytest.fixture
def config_store(config_dir: Path) -> ConfigStore:
    return ConfigStore(config_dir, "boomarr.yml", {"logging": {"dir": ""}})


@pytest.fixture
def auth(config_dir: Path) -> AuthStore:
    return AuthStore(config_dir / "auth.json")


@pytest.fixture
def daemon(config_store: ConfigStore, auth: AuthStore) -> Iterator[Daemon]:
    instance = Daemon(config_store, auth, skip_readonly_check=True)
    yield instance
    instance.state.close()


PUBLIC_CLIENT = ("93.184.216.34", 50000)
LOCAL_CLIENT = ("192.168.1.20", 50000)
CSRF = {"X-Requested-With": "boomarr"}


@pytest.fixture
def web_daemon(daemon: Daemon) -> Daemon:
    """A daemon whose scan queue exists (as if ``main()`` was running)."""
    daemon._queue = asyncio.Queue()
    return daemon


@pytest.fixture
def make_client(web_daemon: Daemon) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def factory(client: tuple[str, int] = PUBLIC_CLIENT) -> TestClient:
        instance = TestClient(create_app(web_daemon), client=client)
        clients.append(instance)
        return instance

    yield factory
    for instance in clients:
        instance.close()


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    """Anonymous client from a public address."""
    return make_client()


@pytest.fixture
def admin(make_client: Callable[..., TestClient], auth: AuthStore) -> TestClient:
    """Client logged in as ``admin`` (password login)."""
    auth.set_credentials("admin", "password1")
    instance = make_client()
    response = instance.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "password1"}
    )
    assert response.status_code == 204
    instance.headers.update(CSRF)
    return instance
