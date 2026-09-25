"""Pipeline orchestration for Boomarr commands.

Defines operation pipelines that compose subsystems (probers, filters,
symlink manager, state store) differently depending on the command being run.
Each command gets a pre-configured pipeline with the correct subsystems,
ordering, and fallback chains.

The ``PipelineFactory`` is the single entry point for building pipelines.
New commands or subsystem implementations are registered here.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from boomarr.config import (
    AudioChannelsFilterConfig,
    AudioCodecFilterConfig,
    Config,
    FFProbeProberConfig,
    LibraryConfig,
    PostProbeFilterConfig,
    PostProbeFilterType,
    PreProbeFilterConfig,
    PreProbeFilterType,
    ProberConfig,
    ProberType,
    ResolutionFilterConfig,
    ScheduleTriggerConfig,
    SQLiteDatabaseConfig,
    TriggerConfig,
    VideoCodecFilterConfig,
    WebhookTriggerConfig,
)
from boomarr.const import (
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_PROBE_WORKERS,
    DEFAULT_SIDECAR_EXTENSIONS,
    AudioLanguageMatchMode,
)
from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.base import PostProbeFilter, PreProbeFilter
from boomarr.filters.file_extension import FileExtensionFilter
from boomarr.filters.media import (
    AudioChannelsFilter,
    AudioCodecFilter,
    ResolutionFilter,
    VideoCodecFilter,
)
from boomarr.models import RemovalGuard
from boomarr.probers.base import MediaProber
from boomarr.probers.ffprobe import FFProbeProber
from boomarr.state import InMemoryStateStore, SQLiteStateStore, StateStore
from boomarr.symlinks import SymlinkManager
from boomarr.triggers.base import TriggerSource
from boomarr.triggers.schedule import ScheduleTrigger
from boomarr.triggers.webhook import WebhookTrigger

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedSymlinkLibrary:
    """A symlink library with resolved post-probe filters and output path."""

    filters: list[PostProbeFilter]
    output_path: Path


@dataclass(frozen=True)
class Pipeline:
    """A fully configured pipeline of subsystems for processing libraries.

    Attributes:
        probers: Ordered list of probers; first successful result wins.
        pre_probe_filters: Filters applied before probing (e.g. extension).
        symlink_libraries: Resolved symlink library definitions with output paths.
        symlinks: The symlink manager for creating/removing links.
        state: The probe cache.
        sidecar_extensions: Extensions of sidecar files linked with media.
        ignore_patterns: fnmatch patterns of names skipped during discovery.
        relative_symlinks: Create relative instead of absolute links.
        probe_workers: Number of files probed in parallel.
    """

    probers: list[MediaProber]
    pre_probe_filters: list[PreProbeFilter] = field(default_factory=list)
    symlink_libraries: list[ResolvedSymlinkLibrary] = field(default_factory=list)
    symlinks: SymlinkManager = field(default_factory=SymlinkManager)
    state: StateStore = field(default_factory=InMemoryStateStore)
    sidecar_extensions: frozenset[str] = frozenset(DEFAULT_SIDECAR_EXTENSIONS)
    ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
    relative_symlinks: bool = False
    probe_workers: int = DEFAULT_PROBE_WORKERS
    removal_guard: RemovalGuard | None = None
    force: bool = False


class PipelineFactory:
    """Builds command-specific pipelines with appropriate subsystem defaults.

    Centralises the decisions about which implementations to use, their
    ordering, and which subsystems each command actually needs.  New prober
    or filter implementations are wired in here — the rest of the codebase
    stays untouched.
    """

    def __init__(
        self,
        *,
        state: StateStore | None = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> None:
        self._state = state or InMemoryStateStore()
        self._dry_run = dry_run
        self._force = force

    @staticmethod
    def build_state_store(config: Config) -> StateStore:
        """Build a StateStore from the database configuration."""
        db = config.database
        if isinstance(db, SQLiteDatabaseConfig):
            return SQLiteStateStore(db.db_file)
        return InMemoryStateStore()

    @staticmethod
    def build_triggers(configs: Sequence[TriggerConfig]) -> list[TriggerSource]:
        """Build trigger source instances from a list of trigger configs."""
        triggers: list[TriggerSource] = []
        for config in configs:
            match config:
                case ScheduleTriggerConfig():
                    triggers.append(
                        ScheduleTrigger(
                            interval=config.interval,
                            run_on_start=config.run_on_start,
                        )
                    )
                case WebhookTriggerConfig():
                    triggers.append(
                        WebhookTrigger(
                            host=config.host,
                            port=config.port,
                            api_key=(
                                config.api_key.get_secret_value()
                                if config.api_key is not None
                                else None
                            ),
                        )
                    )
                case _:
                    raise ValueError(f"Unknown trigger: {config.type!r}")
        return triggers

    @staticmethod
    def _build_probers(configs: Sequence[ProberConfig]) -> list[MediaProber]:
        """Build prober instances from a list of prober configs."""
        probers: list[MediaProber] = []
        for config in configs:
            match config.type:
                case ProberType.FFPROBE:
                    if isinstance(config, FFProbeProberConfig):
                        probers.append(
                            FFProbeProber(path=config.path, timeout=config.timeout)
                        )
                    else:
                        probers.append(FFProbeProber())
                case _:
                    raise ValueError(f"Unknown prober: {config.type!r}")
        return probers

    @staticmethod
    def _build_pre_probe_filters(
        configs: Sequence[PreProbeFilterConfig],
    ) -> list[PreProbeFilter]:
        """Build pre-probe filter instances from a list of filter configs."""
        filters: list[PreProbeFilter] = []
        for config in configs:
            match config.type:
                case PreProbeFilterType.FILE_EXTENSION:
                    extensions_raw = getattr(config, "extensions", None)
                    if extensions_raw is not None:
                        filters.append(
                            FileExtensionFilter(extensions=frozenset(extensions_raw))
                        )
                    else:
                        filters.append(FileExtensionFilter())
                case _:
                    raise ValueError(f"Unknown pre-probe filter: {config.type!r}")
        return filters

    @staticmethod
    def _build_post_probe_filter(config: PostProbeFilterConfig) -> PostProbeFilter:
        """Build a single post-probe filter instance from its config."""
        match config.type:
            case PostProbeFilterType.AUDIO_LANGUAGE:
                lang_entries = getattr(config, "languages", None)
                if not lang_entries:
                    raise ValueError(
                        "audio_language filter requires a 'languages' list"
                    )
                canonical = [entry.code for entry in lang_entries]
                aliases = {
                    entry.code: entry.aliases for entry in lang_entries if entry.aliases
                }
                return AudioLanguageFilter(
                    languages=canonical,
                    aliases=aliases,
                    suffix=config.suffix,
                    mode=getattr(config, "mode", AudioLanguageMatchMode.ANY),
                    invert=getattr(config, "invert", False),
                )
            case PostProbeFilterType.RESOLUTION:
                assert isinstance(config, ResolutionFilterConfig)  # noqa: S101
                return ResolutionFilter(
                    min_height=config.min_height,
                    max_height=config.max_height,
                    suffix=config.suffix,
                    invert=config.invert,
                )
            case PostProbeFilterType.VIDEO_CODEC:
                assert isinstance(config, VideoCodecFilterConfig)  # noqa: S101
                return VideoCodecFilter(
                    config.codecs, suffix=config.suffix, invert=config.invert
                )
            case PostProbeFilterType.AUDIO_CODEC:
                assert isinstance(config, AudioCodecFilterConfig)  # noqa: S101
                return AudioCodecFilter(
                    config.codecs, suffix=config.suffix, invert=config.invert
                )
            case PostProbeFilterType.AUDIO_CHANNELS:
                assert isinstance(config, AudioChannelsFilterConfig)  # noqa: S101
                return AudioChannelsFilter(
                    min_channels=config.min_channels,
                    suffix=config.suffix,
                    invert=config.invert,
                )
            case _:
                raise ValueError(f"Unknown post-probe filter type: {config.type!r}")

    def _resolve_symlink_libraries(
        self,
        config: Config,
        library: LibraryConfig,
    ) -> list[ResolvedSymlinkLibrary]:
        """Resolve symlink library configs into runtime objects.

        Output paths come from :meth:`Config.symlink_library_output`, the
        single source of truth shared with validation and the CLI.
        """
        return [
            ResolvedSymlinkLibrary(
                filters=[self._build_post_probe_filter(fc) for fc in sym_lib.filters],
                output_path=config.symlink_library_output(library, sym_lib),
            )
            for sym_lib in library.symlink_libraries
        ]

    def for_scan(self, config: Config, library: LibraryConfig) -> Pipeline:
        """Build a pipeline for the ``scan`` command.

        Full pipeline: pre-filter → probe → post-filter → symlink → clean stale → persist.
        """
        _LOGGER.debug("Building pipeline for 'scan' on library '%s'", library.name)
        prober_configs = (
            library.probers if library.probers is not None else config.probers
        )
        pre_filter_configs = (
            library.pre_probe_filters
            if library.pre_probe_filters is not None
            else config.pre_probe_filters
        )
        return Pipeline(
            probers=self._build_probers(prober_configs),
            pre_probe_filters=self._build_pre_probe_filters(pre_filter_configs),
            symlink_libraries=self._resolve_symlink_libraries(config, library),
            symlinks=SymlinkManager(dry_run=self._dry_run),
            state=self._state,
            sidecar_extensions=config.sidecar_extensions_for(library),
            ignore_patterns=tuple(config.ignore_patterns_for(library)),
            relative_symlinks=config.relative_symlinks_for(library),
            probe_workers=config.probe_workers,
            removal_guard=config.removal_guard.to_model(),
            force=self._force,
        )

    def for_watch(self, config: Config, library: LibraryConfig) -> Pipeline:
        """Build a pipeline for the ``watch`` command.

        Same as scan but will be used incrementally on filesystem events.
        """
        _LOGGER.debug("Building pipeline for 'watch' on library '%s'", library.name)
        return self.for_scan(config, library)

    def for_clean(self, config: Config, library: LibraryConfig) -> Pipeline:
        """Build a pipeline for the ``clean`` command.

        Only needs the symlink manager and output paths — no probing or filtering.
        """
        _LOGGER.debug("Building pipeline for 'clean' on library '%s'", library.name)
        prober_configs = (
            library.probers if library.probers is not None else config.probers
        )
        return Pipeline(
            probers=self._build_probers(prober_configs),
            pre_probe_filters=[],
            symlink_libraries=self._resolve_symlink_libraries(config, library),
            symlinks=SymlinkManager(dry_run=self._dry_run),
            state=self._state,
        )
