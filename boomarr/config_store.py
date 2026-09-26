"""Reading, validating and writing the configuration file for the web UI.

The YAML file stays the single source of truth: the UI edits it through
this module, and people can still edit it by hand. Writes are validated
first, atomic, keep a ``.bak`` copy and are protected against lost updates
with an ETag. Secrets are never sent to the browser in clear text, and
values that come from environment variables or CLI options are never
written back to the file.
"""

import hashlib
import hmac
import os
import secrets
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, SecretStr
from pydantic_core import PydanticUndefined

from boomarr.config import (
    Config,
    ConfigError,
    LanguageEntry,
    SQLiteDatabaseConfig,
    build_config,
    read_config_file,
)

SECRET_PREFIX = "__secret__:"  # noqa: S105 - marker, not a secret
"""Prefix of masked secret values in documents sent to the UI."""

_HEADER = (
    "# Boomarr configuration. Managed by the web UI; manual edits are fine\n"
    "# and are picked up on restart. Reference:\n"
    "# https://github.com/EuleMitKeule/boomarr/blob/master/docs/configuration.md\n"
)

# Keys that are never written to the file (derived or only set via env/CLI).
_NEVER_WRITTEN = {"config_dir", "config_file"}
_NEVER_WRITTEN_NESTED = {("logging", "dir")}


class ConfigConflictError(Exception):
    """The file changed since the client loaded it (ETag mismatch)."""


class ConfigReadOnlyError(Exception):
    """The configuration file cannot be written (e.g. a Kubernetes ConfigMap)."""


def _is_default(field: Any, value: object) -> bool:
    if field.default is not PydanticUndefined:
        return bool(value == field.default)
    if field.default_factory is not None:
        return bool(value == field.default_factory())
    return False


def serialize(value: object, *, keep_defaults: bool = False) -> Any:
    """Turn config models into plain YAML data, omitting default values.

    ``type`` discriminators are always kept so that lists of typed entries
    (probers, filters, triggers, media servers) stay loadable.
    """
    if isinstance(value, LanguageEntry) and not value.aliases and not keep_defaults:
        return value.code  # "deu" instead of {"code": "deu"}
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        out: dict[str, Any] = {}
        if "type" in fields:  # discriminator first, for readability
            out["type"] = serialize(value.type)  # ty: ignore[unresolved-attribute]
        for name, field in fields.items():
            item = getattr(value, name)
            if name == "type" or (not keep_defaults and _is_default(field, item)):
                continue
            out[name] = serialize(item, keep_defaults=keep_defaults)
        return out
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: serialize(v, keep_defaults=keep_defaults) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [serialize(v, keep_defaults=keep_defaults) for v in value]
    return value


def _get_path(data: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _del_path(data: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    node: Any = data
    for part in parts[:-1]:
        node = node.get(part)
        if not isinstance(node, dict):
            return
    node.pop(parts[-1], None)


def _prune_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if not (isinstance(v, dict) and not v)}


def config_to_file_data(config: Config, raw: dict[str, Any]) -> dict[str, Any]:
    """Return the minimal YAML document that reproduces *config*.

    Values overridden by environment variables or CLI options are restored
    from the previous file content *raw* (or left out), so that secrets
    passed via the environment never end up on disk.
    """
    data: dict[str, Any] = serialize(config)
    for key in _NEVER_WRITTEN:
        data.pop(key, None)
    for section, key in _NEVER_WRITTEN_NESTED:
        data.get(section, {}).pop(key, None)
    database = data.get("database")
    if (
        isinstance(config.database, SQLiteDatabaseConfig)
        and isinstance(database, dict)
        and config.database.dir == config.config_dir.resolve()
    ):
        database.pop("dir", None)
        if database == {"type": "sqlite"}:
            data.pop("database")
    for dotted in sorted(config._env_overrides):
        found, value = _get_path(raw, dotted)
        if found:
            _set_path(data, dotted, value)
        else:
            _del_path(data, dotted)
    return _prune_empty(data)


class SecretMasker:
    """Replaces secrets by opaque tokens and maps tokens back to secrets.

    Tokens are HMACs with a per-process key, so they are stable while the
    process runs (a list can be re-ordered or shortened safely) but reveal
    nothing about the secret.
    """

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def token(self, secret: str) -> str:
        digest = hmac.new(self._key, secret.encode(), hashlib.sha256).hexdigest()
        return f"{SECRET_PREFIX}{digest[:24]}"

    def mask(self, value: object) -> Any:
        if isinstance(value, BaseModel):
            return {
                name: self.mask(getattr(value, name))
                for name in type(value).model_fields
            }
        if isinstance(value, SecretStr):
            return self.token(value.get_secret_value())
        if isinstance(value, list | tuple):
            return [self.mask(v) for v in value]
        if isinstance(value, dict):
            return {k: self.mask(v) for k, v in value.items()}
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return str(value)
        return value

    def _secrets(self, value: object, found: dict[str, str]) -> None:
        if isinstance(value, BaseModel):
            for name in type(value).model_fields:
                self._secrets(getattr(value, name), found)
        elif isinstance(value, SecretStr):
            secret = value.get_secret_value()
            found[self.token(secret)] = secret
        elif isinstance(value, list | tuple):
            for item in value:
                self._secrets(item, found)

    def unmask(self, document: Any, current: Config) -> Any:
        """Replace tokens in *document* by the secrets of *current*.

        Raises:
            ConfigError: for a token that matches no current secret.
        """
        known: dict[str, str] = {}
        self._secrets(current, known)

        def walk(node: Any, loc: list[Any]) -> Any:
            if isinstance(node, dict):
                return {k: walk(v, [*loc, k]) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v, [*loc, i]) for i, v in enumerate(node)]
            if isinstance(node, str) and node.startswith(SECRET_PREFIX):
                if node not in known:
                    raise ConfigError(
                        "A secret value is no longer known, please enter it again.",
                        [{"loc": loc, "msg": "please enter this secret again"}],
                    )
                return known[node]
            return node

        return walk(document, [])


class ConfigStore:
    """Loads, validates and persists the configuration file."""

    def __init__(
        self,
        config_dir: Path,
        file_name: str,
        cli_values: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.file_name = file_name
        self.path = config_dir / file_name
        self._cli_values = cli_values or {}
        self._masker = SecretMasker()
        self.raw: dict[str, Any] = {}
        self.config: Config | None = None

    # -- reading ----------------------------------------------------------

    def load(self) -> Config:
        """(Re-)read the file. Raises :class:`ConfigError` if invalid."""
        raw = read_config_file(self.path)
        config = build_config(raw, self.config_dir, self.file_name, self._cli_values)
        self.raw = raw
        self.config = config
        return config

    @property
    def etag(self) -> str:
        """Hash of the file content, used for optimistic concurrency."""
        try:
            content = self.path.read_bytes()
        except OSError:
            content = b""
        return hashlib.sha256(content).hexdigest()[:32]

    @property
    def writable(self) -> bool:
        """Whether the UI may save changes."""
        if self.path.exists():
            return os.access(self.path, os.W_OK) and os.access(
                self.path.parent, os.W_OK
            )
        return os.access(self.path.parent, os.W_OK)

    def _current(self) -> Config:
        if self.config is None:
            return self.load()
        return self.config

    def document(self) -> dict[str, Any]:
        """Return the configuration for the UI (secrets masked)."""
        config = self._current()
        masked: dict[str, Any] = self._masker.mask(config)
        for key in _NEVER_WRITTEN:
            masked.pop(key, None)
        return {
            "config": masked,
            "etag": self.etag,
            "writable": self.writable,
            "path": str(self.path),
            "env_overrides": sorted(config._env_overrides),
            "warnings": config.warnings,
        }

    # -- validating / writing ---------------------------------------------

    def unmask(self, fragment: Any) -> Any:
        """Replace secret tokens in a partial document (e.g. a connection test)."""
        return self._masker.unmask(fragment, self._current())

    def _candidate(self, document: dict[str, Any]) -> Config:
        if not isinstance(document, dict):
            raise ConfigError("The configuration must be an object.")
        current = self._current()
        data = self._masker.unmask(document, current)
        for dotted in current._env_overrides:
            # Env/CLI values are re-applied by build_config; take the file's
            # own value (if any) so nothing is reported twice.
            found, value = _get_path(self.raw, dotted)
            if found:
                _set_path(data, dotted, value)
            else:
                _del_path(data, dotted)
        for key in _NEVER_WRITTEN:
            data.pop(key, None)
        for section, key in _NEVER_WRITTEN_NESTED:
            if isinstance(data.get(section), dict):
                data[section].pop(key, None)
        return build_config(data, self.config_dir, self.file_name, self._cli_values)

    def validate(self, document: dict[str, Any]) -> Config:
        """Validate a document without saving. Raises :class:`ConfigError`."""
        return self._candidate(document)

    def save(self, document: dict[str, Any], etag: str | None = None) -> Config:
        """Validate and persist *document*; returns the new configuration.

        Raises:
            ConfigError: invalid configuration.
            ConfigConflictError: the file changed since *etag* was read.
            ConfigReadOnlyError: the file cannot be written.
        """
        if etag is not None and etag != self.etag:
            raise ConfigConflictError(
                "The configuration was changed by someone else. Reload and try again."
            )
        candidate = self._candidate(document)
        self._write(config_to_file_data(candidate, self.raw))
        return self.load()

    def export_yaml(self) -> str:
        """Return the raw file content (for backups)."""
        return self.path.read_text(encoding="utf-8")

    def import_yaml(self, text: str) -> Config:
        """Validate and store an uploaded YAML file (restore from backup)."""
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"The file is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("The top level of the file must be a mapping.")
        build_config(data, self.config_dir, self.file_name, self._cli_values)
        self._write_text(text)
        return self.load()

    def _write(self, data: dict[str, Any]) -> None:
        text = _HEADER + yaml.safe_dump(
            data, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
        self._write_text(text)

    def _write_text(self, text: str) -> None:
        if not self.writable:
            raise ConfigReadOnlyError(
                f"'{self.path}' is read-only; change the configuration at its source."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = self.path.stat().st_mode & 0o777 if self.path.exists() else 0o600
        if self.path.exists():
            backup = self.path.with_name(f"{self.path.name}.bak")
            backup.write_bytes(self.path.read_bytes())
            os.chmod(backup, mode)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
