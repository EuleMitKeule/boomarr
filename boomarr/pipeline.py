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
from typing import cast

from boomarr.config import (
    Config,
    LibraryConfig,
    PostProbeFilterConfig,
    PostProbeFilterType,
    PreProbeFilterConfig,
    PreProbeFilterType,
    ProberConfig,
    ProberType,
    SQLiteDatabaseConfig,
)
from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.base import PostProbeFilter, PreProbeFilter
from boomarr.filters.file_extension import FileExtensionFilter
from boomarr.probers.base import MediaProber
from boomarr.probers.ffprobe import FFProbeProber
from boomarr.state import InMemoryStateStore, SQLiteStateStore, StateStore
from boomarr.symlinks import SymlinkManager

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
        state: The state store for tracking processed files.
    """

    probers: list[MediaProber]
    pre_probe_filters: list[PreProbeFilter] = field(default_factory=list)
    symlink_libraries: list[ResolvedSymlinkLibrary] = field(default_factory=list)
    symlinks: SymlinkManager = field(default_factory=SymlinkManager)
    state: StateStore = field(default_factory=InMemoryStateStore)


class PipelineFactory:
    """Builds command-specific pipelines with appropriate subsystem defaults.

    Centralises the decisions about which implementations to use, their
    ordering, and which subsystems each command actually needs.  New prober
    or filter implementations are wired in here — the rest of the codebase
    stays untouched.
    """

    def __init__(self, *, state: StateStore | None = None) -> None:
        self._state = state or InMemoryStateStore()

    @staticmethod
    def build_state_store(config: Config) -> StateStore:
        """Build a StateStore from the database configuration."""
        db = config.database
        if isinstance(db, SQLiteDatabaseConfig):
            return SQLiteStateStore(db.db_file)
        return InMemoryStateStore()

    @staticmethod
    def _build_probers(configs: Sequence[ProberConfig]) -> list[MediaProber]:
        """Build prober instances from a list of prober configs."""
        probers: list[MediaProber] = []
        for config in configs:
            match config.type:
                case ProberType.FFPROBE:
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
                languages = getattr(config, "languages", None)
                if not languages:
                    raise ValueError(
                        "audio_language filter requires a 'languages' list"
                    )
                return AudioLanguageFilter(
                    languages=languages,
                    suffix=config.suffix,
                )
            case _:
                raise ValueError(f"Unknown post-probe filter type: {config.type!r}")

    def _resolve_symlink_libraries(
        self,
        config: Config,
        library: LibraryConfig,
    ) -> list[ResolvedSymlinkLibrary]:
        """Resolve symlink library configs into runtime objects.

        The effective output base is ``library.output_path`` when set,
        otherwise ``config.output_path``.  When using the global output
        path, library name is included in the auto-generated directory
        name to avoid collisions between libraries.
        """
        resolved: list[ResolvedSymlinkLibrary] = []
        base_output = cast(
            Path,
            library.output_path
            if library.output_path is not None
            else config.output_path,
        )

        for sym_lib in library.symlink_libraries:
            filters = [self._build_post_probe_filter(fc) for fc in sym_lib.filters]
            if sym_lib.output_path is not None:
                output_path = sym_lib.output_path
            elif sym_lib.name is not None:
                output_path = base_output / sym_lib.name
            else:
                lib_slug = library.name.lower().replace(" ", "-")
                combined_suffix = "-".join(f.suffix for f in filters)
                output_path = base_output / f"{lib_slug}-{combined_suffix}"
            resolved.append(
                ResolvedSymlinkLibrary(filters=filters, output_path=output_path)
            )
        return resolved

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
            symlinks=SymlinkManager(),
            state=self._state,
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
            symlinks=SymlinkManager(),
            state=self._state,
        )
