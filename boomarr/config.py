"""Configuration management module.

Handles loading, parsing, and validation of Boomarr configuration.
"""

import logging
import os
import sys
import zoneinfo
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

import typer
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from boomarr.const import (
    APP_NAME,
    CONF_CONFIG_DIR,
    CONF_DATABASE,
    CONF_DATABASE_DIR,
    CONF_GENERAL_TZ,
    CONF_GENERAL_UMASK,
    CONF_LIBRARIES,
    CONF_LIBRARY_INPUT_PATH,
    CONF_LIBRARY_NAME,
    CONF_LIBRARY_OUTPUT_PATH,
    CONF_LOGGING,
    CONF_LOGGING_DIR,
    CONF_LOGGING_FILE_NAME,
    CONF_LOGGING_LEVEL,
    CONF_OUTPUT_PATH,
    DEFAULT_DB_DIR,
    DEFAULT_DB_FILE_NAME,
    DEFAULT_FFPROBE_PATH,
    DEFAULT_FFPROBE_TIMEOUT,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_LOG_COLOR,
    DEFAULT_LOG_DATE_FORMAT,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE_NAME,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_ROTATION_BACKUP_COUNT,
    DEFAULT_LOG_ROTATION_ENABLED,
    DEFAULT_LOG_ROTATION_MAX_BYTES,
    DEFAULT_LOG_ROTATION_ROTATE_ON_START,
    DEFAULT_PGID,
    DEFAULT_PRE_PROBE_FILTERS,
    DEFAULT_PROBE_WORKERS,
    DEFAULT_PROBERS,
    DEFAULT_PUID,
    DEFAULT_REMOVAL_GUARD_MAX_PERCENT,
    DEFAULT_REMOVAL_GUARD_MIN_COUNT,
    DEFAULT_SCHEDULE_INTERVAL,
    DEFAULT_SCHEDULE_RUN_ON_START,
    DEFAULT_SIDECAR_EXTENSIONS,
    DEFAULT_TZ,
    DEFAULT_UMASK,
    DEFAULT_WATCH_DEBOUNCE,
    DEFAULT_WEBHOOK_HOST,
    DEFAULT_WEBHOOK_PORT,
    ENV_API_KEY,
    ENV_NOTIFY_URLS,
    ENV_PREFIX_GENERAL,
    ENV_PREFIX_LOG_ROTATION,
    ENV_PREFIX_LOGGING,
    ENV_WEBHOOK_API_KEY,
    AudioLanguageMatchMode,
    DatabaseType,
    LogLevel,
    MediaServerType,
    PostProbeFilterType,
    PreProbeFilterType,
    ProberType,
    TriggerType,
)
from boomarr.filters.media import normalize_codec
from boomarr.models import RemovalGuard

__all__ = [
    "AnyDatabaseConfig",
    "AnyTriggerConfig",
    "DatabaseType",
    "MemoryDatabaseConfig",
    "PostProbeFilterType",
    "PreProbeFilterType",
    "ProberType",
    "SQLiteDatabaseConfig",
    "ScheduleTriggerConfig",
    "TriggerType",
    "WatchConfig",
    "WebhookTriggerConfig",
]

_LOGGER = logging.getLogger(APP_NAME)


class _ConfigModel(BaseModel):
    """Base class for all config models.

    Unknown keys are accepted (so that an outdated or mistyped option does
    not prevent startup) but collected by :meth:`unknown_keys` so that they
    can be reported as warnings.
    """

    model_config = ConfigDict(extra="allow")

    def unknown_keys(self, prefix: str = "") -> list[str]:
        """Return dotted paths of all unknown keys in this model tree."""
        found = [f"{prefix}{key}" for key in (self.model_extra or {})]
        for name in type(self).model_fields:
            value = getattr(self, name)
            items = value if isinstance(value, list) else [value]
            for idx, item in enumerate(items):
                if isinstance(item, _ConfigModel):
                    label = f"{name}[{idx}]" if isinstance(value, list) else name
                    found.extend(item.unknown_keys(f"{prefix}{label}."))
        return found


def _normalize_extension(ext: str) -> str:
    """Return *ext* lower-cased with exactly one leading dot."""
    ext = ext.strip().lower()
    return ext if ext.startswith(".") else f".{ext}"


def _validate_path_component(value: str, what: str) -> str:
    """Ensure *value* can be used as a single directory name."""
    if value in {".", ".."} or "/" in value or "\\" in value or "\0" in value:
        raise ValueError(
            f"{what} '{value}' must be usable as a single directory name "
            f"(no '/', '\\', '.' or '..')"
        )
    return value


class GeneralConfig(_ConfigModel):
    """General sub-configuration for timezone, user/group IDs, and umask."""

    _env_prefix: ClassVar[str] = ENV_PREFIX_GENERAL

    tz: str = Field(default=DEFAULT_TZ, validate_default=True)
    puid: int = Field(default=DEFAULT_PUID, validate_default=True)
    pgid: int = Field(default=DEFAULT_PGID, validate_default=True)
    umask: str = Field(default=DEFAULT_UMASK, validate_default=True)

    @field_validator(CONF_GENERAL_TZ, mode="before")
    @classmethod
    def _coerce_tz(cls, v: object) -> object:
        """Treat empty/whitespace-only strings as None (falls back to default)."""
        if isinstance(v, str) and not v.strip():
            return DEFAULT_TZ
        return v

    @field_validator(CONF_GENERAL_TZ, mode="after")
    @classmethod
    def _validate_tz(cls, v: str) -> str:
        """Validate that the timezone is a known IANA timezone."""
        try:
            zoneinfo.ZoneInfo(v)
        except KeyError:
            raise ValueError(f"Invalid timezone: '{v}'") from None
        return v

    @field_validator(CONF_GENERAL_UMASK, mode="before")
    @classmethod
    def _coerce_umask(cls, v: object) -> object:
        """Convert integer umask values (from YAML) to zero-padded strings."""
        if isinstance(v, int):
            return f"{v:03d}"
        return v

    @field_validator(CONF_GENERAL_UMASK, mode="after")
    @classmethod
    def _validate_umask(cls, v: str) -> str:
        """Validate that the umask is a valid octal string in range 000-777."""
        try:
            val = int(v, 8)
        except ValueError:
            raise ValueError(
                f"Invalid umask '{v}': must be a valid octal string (e.g. '022')"
            ) from None
        if val < 0 or val > 0o777:
            raise ValueError(f"Umask value '{v}' out of range (000-777)")
        return v


class LogRotationConfig(_ConfigModel):
    """Log file rotation sub-configuration."""

    _env_prefix: ClassVar[str] = ENV_PREFIX_LOG_ROTATION

    enabled: bool = Field(default=DEFAULT_LOG_ROTATION_ENABLED, validate_default=True)
    max_bytes: int = Field(
        default=DEFAULT_LOG_ROTATION_MAX_BYTES, validate_default=True
    )
    backup_count: int = Field(
        default=DEFAULT_LOG_ROTATION_BACKUP_COUNT, validate_default=True
    )
    rotate_on_start: bool = Field(
        default=DEFAULT_LOG_ROTATION_ROTATE_ON_START, validate_default=True
    )


class LoggingConfig(_ConfigModel):
    """Logging sub-configuration."""

    _env_prefix: ClassVar[str] = ENV_PREFIX_LOGGING
    _yaml_excluded: ClassVar[frozenset[str]] = frozenset({CONF_LOGGING_DIR})

    level: LogLevel = Field(default=DEFAULT_LOG_LEVEL, validate_default=True)
    format: str = Field(default=DEFAULT_LOG_FORMAT, validate_default=True)
    date_format: str = Field(default=DEFAULT_LOG_DATE_FORMAT, validate_default=True)
    dir: Path | None = Field(default=DEFAULT_LOG_DIR, validate_default=True)
    file_name: str | None = Field(default=DEFAULT_LOG_FILE_NAME, validate_default=True)
    color: bool = Field(default=DEFAULT_LOG_COLOR, validate_default=True)
    rotation: LogRotationConfig = Field(
        default_factory=LogRotationConfig, validate_default=True
    )

    @property
    def log_file(self) -> Path | None:
        """Return the resolved log file path, or None if file logging is disabled."""
        if self.dir is None or self.file_name is None:
            return None
        return self.dir / self.file_name

    @field_validator(CONF_LOGGING_LEVEL, mode="before")
    @classmethod
    def _coerce_level(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator(CONF_LOGGING_DIR, CONF_LOGGING_FILE_NAME, mode="before")
    @classmethod
    def _coerce_nullable_str(cls, v: object) -> object:
        """Treat empty-string values as None (disables file logging)."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator(CONF_LOGGING_DIR, mode="after")
    @classmethod
    def _resolve_dir_to_absolute(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v


def _coerce_typed_list(v: object) -> object:
    """Coerce plain string items in a list to ``{'type': item}`` dicts.

    Allows YAML entries like ``- ffprobe`` in addition to
    ``- type: ffprobe`` for configs without required arguments.
    StrEnum members are also strings, so they are handled by the same branch.
    """
    if isinstance(v, list):
        return [{"type": item} if isinstance(item, str) else item for item in v]
    return v


class ProberConfig(_ConfigModel):
    """Base class for prober configurations."""

    type: ProberType


class FFProbeProberConfig(ProberConfig):
    """Configuration for the FFProbe prober."""

    type: Literal[ProberType.FFPROBE] = ProberType.FFPROBE
    path: str = DEFAULT_FFPROBE_PATH
    timeout: float = Field(default=DEFAULT_FFPROBE_TIMEOUT, gt=0)


AnyProberConfig = FFProbeProberConfig


class PreProbeFilterConfig(_ConfigModel):
    """Base class for pre-probe filter configurations."""

    type: PreProbeFilterType


class FileExtensionFilterConfig(PreProbeFilterConfig):
    """Configuration for the file-extension pre-probe filter."""

    type: Literal[PreProbeFilterType.FILE_EXTENSION] = PreProbeFilterType.FILE_EXTENSION
    extensions: list[str] | None = None

    @field_validator("extensions", mode="after")
    @classmethod
    def _normalize_extensions(cls, v: list[str] | None) -> list[str] | None:
        """Accept ``mkv``, ``.MKV`` and ``.mkv`` alike."""
        if v is None:
            return v
        return [_normalize_extension(ext) for ext in v]


AnyPreProbeFilterConfig = FileExtensionFilterConfig


class PostProbeFilterConfig(_ConfigModel):
    """Base class for post-probe filter configurations."""

    type: PostProbeFilterType
    suffix: str | None = None
    invert: bool = False

    @field_validator("suffix", mode="after")
    @classmethod
    def _validate_suffix(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_path_component(v, "Filter suffix")
        return v

    def effective_suffix(self) -> str:
        """Return the suffix used for automatic output directory naming."""
        if self.suffix is not None:
            return self.suffix
        base = self.default_suffix()
        return f"not-{base}" if self.invert else base

    def default_suffix(self) -> str:
        """Return the suffix derived from the filter settings."""
        return self.type.value


class LanguageEntry(_ConfigModel):
    """A language code with optional alias codes that also match."""

    code: str
    aliases: list[str] = Field(default_factory=list)


class AudioLanguageFilterConfig(PostProbeFilterConfig):
    """Configuration for the audio-language post-probe filter."""

    type: Literal[PostProbeFilterType.AUDIO_LANGUAGE] = (
        PostProbeFilterType.AUDIO_LANGUAGE
    )
    languages: list[LanguageEntry]
    mode: AudioLanguageMatchMode = AudioLanguageMatchMode.ANY

    def default_suffix(self) -> str:
        """Return the configured language codes joined by ``-``.

        Must stay stable across releases: it names existing output folders.
        """
        return "-".join(sorted(entry.code.strip().lower() for entry in self.languages))

    @field_validator("languages", mode="before")
    @classmethod
    def _coerce_language_entries(cls, v: object) -> object:
        """Allow plain strings as shorthand for ``{code: str}``."""
        if isinstance(v, list):
            return [{"code": item} if isinstance(item, str) else item for item in v]
        return v

    @field_validator("languages", mode="after")
    @classmethod
    def _validate_languages_not_empty(
        cls, v: list[LanguageEntry]
    ) -> list[LanguageEntry]:
        if not v:
            raise ValueError("at least one language is required")
        return v


_RESOLUTION_ALIASES: dict[str, int] = {
    "sd": 480,
    "hd": 720,
    "fhd": 1080,
    "uhd": 2160,
    "4k": 2160,
    "8k": 4320,
}


def _parse_height(value: object) -> object:
    """Accept ``1080``, ``"1080p"``, ``"4k"`` or ``"uhd"``."""
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _RESOLUTION_ALIASES:
            return _RESOLUTION_ALIASES[text]
        text = text.removesuffix("p")
        if text.isdigit():
            return int(text)
    return value


class ResolutionFilterConfig(PostProbeFilterConfig):
    """Video resolution bounds (inclusive, by 16:9-equivalent height)."""

    type: Literal[PostProbeFilterType.RESOLUTION] = PostProbeFilterType.RESOLUTION
    min_height: int | None = Field(default=None, gt=0)
    max_height: int | None = Field(default=None, gt=0)

    @field_validator("min_height", "max_height", mode="before")
    @classmethod
    def _coerce_height(cls, v: object) -> object:
        return _parse_height(v)

    @model_validator(mode="after")
    def _validate_bounds(self) -> ResolutionFilterConfig:
        if self.min_height is None and self.max_height is None:
            raise ValueError("resolution filter needs min_height and/or max_height")
        if (
            self.min_height is not None
            and self.max_height is not None
            and self.min_height > self.max_height
        ):
            raise ValueError("min_height must not be greater than max_height")
        return self

    def default_suffix(self) -> str:
        if self.min_height is not None and self.max_height is not None:
            return f"{self.min_height}p-{self.max_height}p"
        if self.min_height is not None:
            return f"{self.min_height}p-plus"
        return f"max-{self.max_height}p"


class _CodecFilterConfig(PostProbeFilterConfig):
    codecs: list[str]

    @field_validator("codecs", mode="after")
    @classmethod
    def _validate_codecs(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one codec is required")
        return v

    def default_suffix(self) -> str:
        return "-".join(sorted({normalize_codec(c) for c in self.codecs}))


class VideoCodecFilterConfig(_CodecFilterConfig):
    """Matches files with a video track in one of ``codecs`` (hevc, h264, av1…)."""

    type: Literal[PostProbeFilterType.VIDEO_CODEC] = PostProbeFilterType.VIDEO_CODEC


class AudioCodecFilterConfig(_CodecFilterConfig):
    """Matches files with an audio track in one of ``codecs`` (truehd, eac3…)."""

    type: Literal[PostProbeFilterType.AUDIO_CODEC] = PostProbeFilterType.AUDIO_CODEC


class AudioChannelsFilterConfig(PostProbeFilterConfig):
    """Matches files with an audio track of at least ``min_channels`` channels."""

    type: Literal[PostProbeFilterType.AUDIO_CHANNELS] = (
        PostProbeFilterType.AUDIO_CHANNELS
    )
    min_channels: int = Field(gt=0)

    def default_suffix(self) -> str:
        return f"{self.min_channels}ch"


AnyPostProbeFilterConfig = Annotated[
    AudioLanguageFilterConfig
    | ResolutionFilterConfig
    | VideoCodecFilterConfig
    | AudioCodecFilterConfig
    | AudioChannelsFilterConfig,
    Field(discriminator="type"),
]


class TriggerConfig(_ConfigModel):
    """Base class for trigger source configurations."""

    type: TriggerType


class ScheduleTriggerConfig(TriggerConfig):
    """Configuration for the periodic schedule trigger.

    Triggers a full rescan at a fixed interval.  When ``run_on_start``
    is ``True`` (the default) an immediate scan is emitted before the
    first interval elapses.
    """

    type: Literal[TriggerType.SCHEDULE] = TriggerType.SCHEDULE
    interval: int = Field(default=DEFAULT_SCHEDULE_INTERVAL, validate_default=True)
    run_on_start: bool = Field(
        default=DEFAULT_SCHEDULE_RUN_ON_START, validate_default=True
    )

    @field_validator("interval", mode="after")
    @classmethod
    def _validate_interval_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("interval must be a positive number of seconds")
        return v


def _api_key_from_env(v: object) -> object:
    """Fall back to ``BOOMARR_API_KEY``/``WEBHOOK_API_KEY``; empty means None."""
    if v is None:
        v = os.environ.get(ENV_API_KEY) or os.environ.get(ENV_WEBHOOK_API_KEY)
    if isinstance(v, str) and not v.strip():
        return None
    return v


class ServerConfig(_ConfigModel):
    """Built-in HTTP server (watch mode): health, metrics, scan API, webhooks."""

    enabled: bool = False
    host: str = DEFAULT_WEBHOOK_HOST
    port: int = Field(default=DEFAULT_WEBHOOK_PORT, ge=1, le=65535)
    api_key: SecretStr | None = Field(default=None, validate_default=True)
    metrics_auth: bool = False

    @field_validator("api_key", mode="before")
    @classmethod
    def _coerce_api_key(cls, v: object) -> object:
        return _api_key_from_env(v)


class WebhookTriggerConfig(TriggerConfig):
    """Deprecated alias for ``server: {enabled: true, ...}``."""

    type: Literal[TriggerType.WEBHOOK] = TriggerType.WEBHOOK
    host: str = DEFAULT_WEBHOOK_HOST
    port: int = Field(default=DEFAULT_WEBHOOK_PORT, ge=1, le=65535)
    api_key: SecretStr | None = Field(default=None, validate_default=True)

    @field_validator("api_key", mode="before")
    @classmethod
    def _coerce_empty_api_key(cls, v: object) -> object:
        return _api_key_from_env(v)


AnyTriggerConfig = Annotated[
    ScheduleTriggerConfig | WebhookTriggerConfig, Field(discriminator="type")
]


class WatchConfig(_ConfigModel):
    """Watch-mode sub-configuration."""

    _env_prefix: ClassVar[str] = "WATCH"

    debounce: float = Field(default=DEFAULT_WATCH_DEBOUNCE, validate_default=True)

    @field_validator("debounce", mode="after")
    @classmethod
    def _validate_debounce_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("debounce must be non-negative")
        return v


class RemovalGuardConfig(_ConfigModel):
    """Protection against accidental mass removal of symlinks.

    A scan refuses to remove symlinks from an output directory when it would
    remove more than ``min_count`` links *and* more than ``max_percent`` of
    them. ``boomarr scan --force`` overrides it once; ``max_percent: 100``
    disables it.
    """

    max_percent: float = Field(default=DEFAULT_REMOVAL_GUARD_MAX_PERCENT, gt=0, le=100)
    min_count: int = Field(default=DEFAULT_REMOVAL_GUARD_MIN_COUNT, ge=0)

    def to_model(self) -> RemovalGuard | None:
        """Return the runtime guard, or None when disabled."""
        if self.max_percent >= 100:
            return None
        return RemovalGuard(max_percent=self.max_percent, min_count=self.min_count)


class PathMapping(_ConfigModel):
    """Translate a path prefix as Boomarr sees it into another system's view."""

    local: Path
    remote: str

    def to_remote(self, path: Path) -> str | None:
        """Return *path* translated to the remote view, or None if unmapped."""
        if not path.is_relative_to(self.local):
            return None
        rel = path.relative_to(self.local).as_posix()
        return self.remote.rstrip("/") + ("" if rel == "." else f"/{rel}")

    def to_local(self, remote_path: str) -> Path | None:
        """Return a remote path translated to Boomarr's view, or None."""
        prefix = self.remote.rstrip("/")
        if remote_path != prefix and not remote_path.startswith(prefix + "/"):
            return None
        return self.local / remote_path[len(prefix) :].lstrip("/")


def map_to_remote(path: Path, mappings: list[PathMapping]) -> str:
    """Apply the most specific matching mapping (identity if none matches)."""
    for mapping in sorted(mappings, key=lambda m: len(m.local.parts), reverse=True):
        remote = mapping.to_remote(path)
        if remote is not None:
            return remote
    return str(path)


def map_to_local(remote_path: str, mappings: list[PathMapping]) -> Path:
    """Inverse of :func:`map_to_remote`."""
    for mapping in sorted(mappings, key=lambda m: len(m.remote), reverse=True):
        local = mapping.to_local(remote_path)
        if local is not None:
            return local
    return Path(remote_path)


class NotificationsConfig(_ConfigModel):
    """Notifications via Apprise (https://github.com/caronc/apprise/wiki)."""

    urls: list[SecretStr] = Field(default_factory=list, validate_default=True)
    on_changes: bool = False
    on_errors: bool = True
    on_blocked: bool = True

    @field_validator("urls", mode="before")
    @classmethod
    def _urls_from_env(cls, v: object) -> object:
        """Fall back to the whitespace separated ``BOOMARR_NOTIFY_URLS``."""
        if v is None or v == []:
            env = os.environ.get(ENV_NOTIFY_URLS, "")
            return env.split()
        return v


class _MediaServerConfig(_ConfigModel):
    url: str
    path_mappings: list[PathMapping] = Field(default_factory=list)
    timeout: float = Field(default=10.0, gt=0)

    @field_validator("url", mode="after")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v.rstrip("/")


class PlexConfig(_MediaServerConfig):
    """Refresh Plex library sections containing changed output folders."""

    type: Literal[MediaServerType.PLEX] = MediaServerType.PLEX
    token: SecretStr


class JellyfinConfig(_MediaServerConfig):
    """Notify Jellyfin about changed output folders."""

    type: Literal[MediaServerType.JELLYFIN] = MediaServerType.JELLYFIN
    api_key: SecretStr


class EmbyConfig(_MediaServerConfig):
    """Notify Emby about changed output folders."""

    type: Literal[MediaServerType.EMBY] = MediaServerType.EMBY
    api_key: SecretStr


AnyMediaServerConfig = Annotated[
    PlexConfig | JellyfinConfig | EmbyConfig, Field(discriminator="type")
]


class SymlinkLibraryConfig(_ConfigModel):
    """Configuration for a single symlink library output."""

    name: str | None = None
    filters: list[AnyPostProbeFilterConfig]
    output_path: Path | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_path_component(v, "Symlink library name")
        return v

    @field_validator("filters", mode="after")
    @classmethod
    def _validate_filters_not_empty(
        cls,
        v: list[AnyPostProbeFilterConfig],
    ) -> list[AnyPostProbeFilterConfig]:
        if not v:
            raise ValueError("Symlink library must have at least one filter")
        return v

    @field_validator("output_path", mode="after")
    @classmethod
    def _resolve_output_path(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v


class LibraryConfig(_ConfigModel):
    """Per-library configuration."""

    name: str
    input_path: Path
    output_path: Path | None = None
    probers: list[AnyProberConfig] | None = None
    pre_probe_filters: list[AnyPreProbeFilterConfig] | None = None
    symlink_libraries: list[SymlinkLibraryConfig]
    sidecar_extensions: list[str] | None = None
    ignore_patterns: list[str] | None = None
    relative_symlinks: bool | None = None

    @field_validator("sidecar_extensions", mode="after")
    @classmethod
    def _normalize_sidecar_extensions(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else [_normalize_extension(ext) for ext in v]

    @field_validator("probers", "pre_probe_filters", mode="before")
    @classmethod
    def _coerce_to_typed_dicts(cls, v: object) -> object:
        return _coerce_typed_list(v)

    @field_validator(CONF_LIBRARY_NAME, mode="after")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Library name must not be empty")
        return _validate_path_component(v.strip(), "Library name")

    @field_validator(CONF_LIBRARY_INPUT_PATH, mode="after")
    @classmethod
    def _resolve_input_path(cls, v: Path) -> Path:
        return v.resolve()

    @field_validator(CONF_LIBRARY_OUTPUT_PATH, mode="after")
    @classmethod
    def _resolve_output_path(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v

    @field_validator("symlink_libraries", mode="after")
    @classmethod
    def _validate_symlink_libraries_not_empty(
        cls,
        v: list[SymlinkLibraryConfig],
    ) -> list[SymlinkLibraryConfig]:
        if not v:
            raise ValueError("Library must have at least one symlink library")
        return v


def _prober_config_from_name(prober_type: ProberType | str) -> AnyProberConfig:
    """Build the appropriate ProberConfig subclass from a prober type (enum or string)."""
    match prober_type:
        case ProberType.FFPROBE:
            return FFProbeProberConfig()
        case _:
            raise ValueError(f"Unknown prober type: {prober_type!r}")


def _pre_probe_filter_config_from_name(
    filter_type: PreProbeFilterType | str,
) -> AnyPreProbeFilterConfig:
    """Build the appropriate PreProbeFilterConfig subclass from a filter type (enum or string)."""
    match filter_type:
        case PreProbeFilterType.FILE_EXTENSION:
            return FileExtensionFilterConfig()
        case _:
            raise ValueError(f"Unknown pre-probe filter type: {filter_type!r}")


class MemoryDatabaseConfig(_ConfigModel):
    """In-memory (non-persistent) database backend configuration."""

    type: Literal[DatabaseType.MEMORY] = DatabaseType.MEMORY


class SQLiteDatabaseConfig(_ConfigModel):
    """SQLite database backend configuration."""

    type: Literal[DatabaseType.SQLITE] = DatabaseType.SQLITE
    dir: Path = Field(default=DEFAULT_DB_DIR, validate_default=True)
    file_name: str = Field(default=DEFAULT_DB_FILE_NAME)

    @property
    def db_file(self) -> Path:
        """Return the resolved path to the SQLite database file."""
        return self.dir / self.file_name

    @field_validator(CONF_DATABASE_DIR, mode="after")
    @classmethod
    def _resolve_dir_to_absolute(cls, v: Path) -> Path:
        return v.resolve()


AnyDatabaseConfig = MemoryDatabaseConfig | SQLiteDatabaseConfig


class Config(_ConfigModel):
    """Boomarr root configuration."""

    config_dir: Path
    config_file: str
    general: GeneralConfig
    logging: LoggingConfig
    database: AnyDatabaseConfig = Field(
        default_factory=SQLiteDatabaseConfig, discriminator="type"
    )
    output_path: Path | None = None
    watch: WatchConfig = Field(default_factory=WatchConfig)
    probers: list[AnyProberConfig] = Field(
        default_factory=lambda: [_prober_config_from_name(n) for n in DEFAULT_PROBERS],
    )
    pre_probe_filters: list[AnyPreProbeFilterConfig] = Field(
        default_factory=lambda: [
            _pre_probe_filter_config_from_name(n) for n in DEFAULT_PRE_PROBE_FILTERS
        ],
    )
    triggers: list[AnyTriggerConfig] = Field(
        default_factory=lambda: list[AnyTriggerConfig]([ScheduleTriggerConfig()])
    )
    libraries: list[LibraryConfig] = Field(default_factory=list)
    sidecar_extensions: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SIDECAR_EXTENSIONS)
    )
    ignore_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS)
    )
    relative_symlinks: bool = False
    probe_workers: int = Field(default=DEFAULT_PROBE_WORKERS, ge=1, le=64)
    removal_guard: RemovalGuardConfig = Field(default_factory=RemovalGuardConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    media_servers: list[AnyMediaServerConfig] = Field(default_factory=list)

    _warnings: list[str] = PrivateAttr(default_factory=list)

    @field_validator("sidecar_extensions", mode="after")
    @classmethod
    def _normalize_sidecar_extensions(cls, v: list[str]) -> list[str]:
        return [_normalize_extension(ext) for ext in v]

    @property
    def warnings(self) -> list[str]:
        """Human-readable warnings collected while loading the config."""
        return [
            *self._warnings,
            *(
                f"Unknown config option '{key}' is ignored (typo or outdated option?)"
                for key in self.unknown_keys()
            ),
        ]

    def library_output_base(self, library: LibraryConfig) -> Path | None:
        """Return the base output directory for *library*."""
        return (
            library.output_path if library.output_path is not None else self.output_path
        )

    def symlink_library_output(
        self, library: LibraryConfig, sym_lib: SymlinkLibraryConfig
    ) -> Path:
        """Return the effective output directory of a symlink library.

        This is the single source of truth for output path resolution:
        explicit ``output_path`` > ``<base>/<name>`` >
        ``<base>/<library-slug>-<filter suffixes>``.
        """
        if sym_lib.output_path is not None:
            return sym_lib.output_path
        base = self.library_output_base(library)
        if base is None:  # pragma: no cover - prevented by validation
            raise ValueError(f"Library '{library.name}' has no output path")
        if sym_lib.name is not None:
            return base / sym_lib.name
        lib_slug = library.name.lower().replace(" ", "-")
        combined_suffix = "-".join(f.effective_suffix() for f in sym_lib.filters)
        return base / f"{lib_slug}-{combined_suffix}"

    def sidecar_extensions_for(self, library: LibraryConfig) -> frozenset[str]:
        """Return the sidecar extensions in effect for *library*."""
        exts = (
            library.sidecar_extensions
            if library.sidecar_extensions is not None
            else self.sidecar_extensions
        )
        return frozenset(exts)

    def ignore_patterns_for(self, library: LibraryConfig) -> list[str]:
        """Return the discovery ignore patterns in effect for *library*."""
        if library.ignore_patterns is not None:
            return list(library.ignore_patterns)
        return list(self.ignore_patterns)

    def relative_symlinks_for(self, library: LibraryConfig) -> bool:
        """Return whether *library* uses relative symlink targets."""
        if library.relative_symlinks is not None:
            return library.relative_symlinks
        return self.relative_symlinks

    @field_validator("probers", "pre_probe_filters", "triggers", mode="before")
    @classmethod
    def _coerce_to_typed_dicts(cls, v: object) -> object:
        return _coerce_typed_list(v)

    @field_validator(CONF_CONFIG_DIR, mode="after")
    @classmethod
    def _resolve_config_dir_to_absolute(cls, v: Path) -> Path:
        """Convert config directory path to absolute."""
        return v.resolve()

    @field_validator(CONF_OUTPUT_PATH, mode="after")
    @classmethod
    def _resolve_output_path(cls, v: Path | None) -> Path | None:
        if v is not None:
            return v.resolve()
        return v

    @field_validator("probers", mode="after")
    @classmethod
    def _validate_probers_not_empty(
        cls, v: list[AnyProberConfig]
    ) -> list[AnyProberConfig]:
        if not v:
            raise ValueError("At least one prober is required")
        return v

    @field_validator(CONF_LIBRARIES, mode="after")
    @classmethod
    def _validate_unique_library_names(
        cls, v: list[LibraryConfig]
    ) -> list[LibraryConfig]:
        names = [lib.name for lib in v]
        if len(names) != len(set(names)):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate library names: {set(dupes)}")
        return v

    @model_validator(mode="after")
    def _migrate_webhook_trigger(self) -> Config:
        """Turn a legacy ``type: webhook`` trigger into ``server`` settings."""
        webhooks = [t for t in self.triggers if isinstance(t, WebhookTriggerConfig)]
        if not webhooks:
            return self
        if len(webhooks) > 1:
            raise ValueError("Only one webhook trigger is supported; use 'server'")
        hook = webhooks[0]
        self.triggers = [
            t for t in self.triggers if not isinstance(t, WebhookTriggerConfig)
        ]
        if not self.server.enabled:
            self.server = ServerConfig(
                enabled=True, host=hook.host, port=hook.port, api_key=hook.api_key
            )
        self._warnings.append(
            "The 'webhook' trigger is deprecated; use the 'server' section "
            "(server: {enabled: true, port: ..., api_key: ...}) instead."
        )
        return self

    @model_validator(mode="after")
    def _validate_output_paths(self) -> Config:
        """Ensure every library can resolve an output path.

        Either the global ``output_path`` is set, or each library provides
        its own ``output_path``, or every symlink library of a library has an
        explicit ``output_path``.
        """
        if self.output_path is None:
            missing = [
                lib.name
                for lib in self.libraries
                if lib.output_path is None
                and any(sym.output_path is None for sym in lib.symlink_libraries)
            ]
            if missing:
                raise ValueError(
                    f"Global output_path is not set and these libraries "
                    f"are missing output_path: {missing}"
                )
        return self

    @model_validator(mode="after")
    def _validate_no_path_overlap(self) -> Config:
        """Reject dangerous or conflicting input/output path layouts.

        * No output directory may equal, contain, or live inside *any*
          library's input path (recursive loops / cleanup touching sources).
        * Every symlink library needs its own output directory, and output
          directories must not be nested inside each other (otherwise the
          cleanup of one library would fight with the other).
        """
        if self.output_path is None and any(
            lib.output_path is None
            and any(sym.output_path is None for sym in lib.symlink_libraries)
            for lib in self.libraries
        ):
            return self  # reported by _validate_output_paths

        inputs = [(lib.name, lib.input_path) for lib in self.libraries]
        outputs: list[tuple[str, str, Path]] = []
        for lib in self.libraries:
            base = self.library_output_base(lib)
            if base is not None:
                outputs.append((lib.name, "base output", base))
            for sym_lib in lib.symlink_libraries:
                outputs.append(
                    (
                        lib.name,
                        "symlink library output",
                        self.symlink_library_output(lib, sym_lib),
                    )
                )

        for lib_name, label, output_path in outputs:
            for input_name, input_path in inputs:
                _check_path_overlap(
                    input_path, output_path, lib_name, label, input_name
                )

        sym_outputs = [o for o in outputs if o[1] == "symlink library output"]
        for idx, (name_a, _, path_a) in enumerate(sym_outputs):
            for name_b, _, path_b in sym_outputs[idx + 1 :]:
                if path_a == path_b:
                    raise ValueError(
                        f"Symlink libraries of '{name_a}' and '{name_b}' resolve to "
                        f"the same output directory '{path_a}'. Give them distinct "
                        f"names or output paths."
                    )
                if path_a.is_relative_to(path_b) or path_b.is_relative_to(path_a):
                    raise ValueError(
                        f"Symlink library output directories '{path_a}' "
                        f"('{name_a}') and '{path_b}' ('{name_b}') are nested "
                        f"inside each other."
                    )
        return self


def _check_path_overlap(
    input_path: Path,
    output_path: Path,
    lib_name: str,
    label: str,
    input_lib_name: str | None = None,
) -> None:
    """Raise ValueError if input and output paths overlap.

    Checks three conditions:
    1. output == input (same directory)
    2. output is inside input (would cause recursive scanning)
    3. input is inside output (symlink cleanup could affect source)
    """
    owner = (
        ""
        if input_lib_name is None or input_lib_name == lib_name
        else f" of library '{input_lib_name}'"
    )
    if output_path.is_relative_to(input_path):
        raise ValueError(
            f"Library '{lib_name}': {label} '{output_path}' is inside "
            f"input_path '{input_path}'{owner}. Output paths must not overlap "
            f"with input paths to prevent recursive symlink loops or "
            f"accidental data loss."
        )
    if input_path.is_relative_to(output_path):
        raise ValueError(
            f"Library '{lib_name}': input_path '{input_path}'{owner} is inside "
            f"{label} '{output_path}'. Output paths must not overlap "
            f"with input paths to prevent accidental modification of "
            f"source files during cleanup."
        )


_config: Config | None = None


def get_config() -> Config:
    """Return the loaded Config singleton.

    Raises:
        RuntimeError: If load_config() has not been called yet.
    """
    if _config is None:
        raise RuntimeError("Config has not been loaded yet. Call load_config() first.")
    return _config


def _to_yaml_serializable(obj: Any) -> Any:
    """Recursively convert enums and other non-YAML types to YAML-serializable forms."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _to_yaml_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_yaml_serializable(v) for v in obj]
    return obj


def _apply_env_vars(
    model_cls: type[BaseModel],
    yaml_data: dict[str, Any],
    config_file_name: str,
    field_name: str,
) -> dict[str, Any]:
    """Overlay environment variables onto ``yaml_data`` for ``model_cls``.

    The env var prefix is read from the model class's ``_env_prefix`` attribute
    if present, otherwise defaults to the field name in uppercase.
    Field names are derived as ``f"{prefix}_{field_name}".upper()``.

    Warns when the same field is supplied by both the config file
    and an env var (the env var wins).

    Args:
        model_cls: The Pydantic model whose fields to inspect.
        yaml_data: Values already loaded from the config file.
        config_file_name: File name used in the warning message.
        field_name: The name of the field in the parent config class.

    Returns:
        A new dict with env var values overlaid on top of yaml_data.
    """
    prefix: str = getattr(model_cls, "_env_prefix", field_name.upper())
    merged = dict(yaml_data)
    for name, field_info in model_cls.model_fields.items():
        if isinstance(field_info.annotation, type) and issubclass(
            field_info.annotation, BaseModel
        ):
            nested_yaml = merged.get(name) or {}
            merged[name] = _apply_env_vars(
                field_info.annotation, nested_yaml, config_file_name, name
            )
            continue
        env_var = f"{prefix}_{name}".upper() if prefix else name.upper()
        env_value = os.environ.get(env_var)
        if env_value is not None:
            if name in yaml_data:
                display_prefix = prefix if prefix else field_name.upper()
                _LOGGER.warning(
                    "'%s %s' is set in both '%s' (%r) and %s (%r). Env var takes precedence.",
                    display_prefix,
                    name,
                    config_file_name,
                    yaml_data[name],
                    env_var,
                    env_value,
                )
            merged[name] = env_value
    return merged


def _write_config_template(config_path: Path) -> None:
    """Create *config_path* from the bundled, fully commented example config."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        template = (
            resources.files("boomarr")
            .joinpath("config.example.yml")
            .read_text(encoding="utf-8")
        )
    except OSError:  # pragma: no cover - packaging error
        template = ""
    config_path.write_text(template, encoding="utf-8")
    _LOGGER.warning(
        "No config file found, created a template at '%s'. "
        "Edit it to configure your libraries.",
        config_path,
    )


def load_config(
    config_dir: Path,
    config_file_name: str,
    log_level: LogLevel | None = None,
    log_dir: Path | str | None = None,
    log_file_name: str | None = None,
) -> Config:
    """Load and validate configuration from all sources.

    Exits:
        Calls sys.exit() with a human-readable error on validation failure.

    Returns:
        The validated Config singleton.
    """
    global _config

    config_path = config_dir / config_file_name
    cli_values: dict[str, dict[str, Any]] = {}
    logging_cli: dict[str, Any] = {}
    if log_level is not None:
        logging_cli[CONF_LOGGING_LEVEL] = log_level
    if log_dir is not None:
        logging_cli[CONF_LOGGING_DIR] = log_dir
    if log_file_name is not None:
        logging_cli[CONF_LOGGING_FILE_NAME] = log_file_name
    if logging_cli:
        cli_values[CONF_LOGGING] = logging_cli

    if not config_path.is_file():
        _write_config_template(config_path)

    try:
        with config_path.open(encoding="utf-8") as config_file:
            yaml_data = yaml.safe_load(config_file) or {}
    except yaml.YAMLError as exc:
        typer.echo(f"Error parsing config file '{config_path}':\n{exc}", err=True)
        sys.exit(1)
    if not isinstance(yaml_data, dict):
        typer.echo(
            f"Error in config file '{config_path}': the top level must be a "
            f"mapping of options, got {type(yaml_data).__name__}.",
            err=True,
        )
        sys.exit(1)

    warnings: list[str] = []
    sub_configs: dict[str, Any] = {}
    for field_name, field_info in Config.model_fields.items():
        if not (
            isinstance(field_info.annotation, type)
            and issubclass(field_info.annotation, BaseModel)
        ):
            continue
        yaml_sub = yaml_data.get(field_name) or {}
        if not isinstance(yaml_sub, dict):
            typer.echo(
                f"Error in config file '{config_path}': '{field_name}' must be a "
                f"mapping of options.",
                err=True,
            )
            sys.exit(1)
        yaml_excluded: frozenset[str] = getattr(
            field_info.annotation, "_yaml_excluded", frozenset()
        )
        for key in sorted(yaml_excluded & yaml_sub.keys()):
            warnings.append(
                f"'{field_name}.{key}' cannot be set in the config file and is "
                f"ignored; use the corresponding environment variable or CLI option."
            )
        yaml_sub = {k: v for k, v in yaml_sub.items() if k not in yaml_excluded}
        sub_merged = _apply_env_vars(
            field_info.annotation, yaml_sub, config_file_name, field_name
        )
        sub_merged.update(cli_values.get(field_name) or {})
        sub_configs[field_name] = sub_merged

    reserved = {CONF_CONFIG_DIR, "config_file", CONF_DATABASE, *sub_configs}
    extra_fields: dict[str, Any] = {
        key: value
        for key, value in yaml_data.items()
        if key not in reserved and value is not None
    }
    for key in sorted(extra_fields.keys() - Config.model_fields.keys()):
        warnings.append(
            f"Unknown config option '{key}' is ignored (typo or outdated option?)"
        )
        del extra_fields[key]

    database_raw = yaml_data.get(CONF_DATABASE)
    resolved_config_dir = config_dir.resolve()
    if database_raw is None:
        extra_fields[CONF_DATABASE] = {
            "type": DatabaseType.SQLITE,
            "dir": str(resolved_config_dir),
        }
    else:
        db_raw = dict(database_raw)
        db_type = str(db_raw.get("type", DatabaseType.SQLITE))
        if db_type == DatabaseType.SQLITE and "dir" not in db_raw:
            db_raw["dir"] = str(resolved_config_dir)
        extra_fields[CONF_DATABASE] = db_raw

    try:
        _config = Config(
            config_dir=config_dir,
            config_file=config_file_name,
            **sub_configs,
            **extra_fields,
        )
        _config._warnings.extend(warnings)
    except ValidationError as exc:
        typer.echo(f"Error validating config file '{config_path}':", err=True)
        typer.echo(exc, err=True)
        sys.exit(1)

    return _config
