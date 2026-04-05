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
from dataclasses import dataclass, field

from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.base import MediaFilter
from boomarr.filters.file_extension import FileExtensionFilter
from boomarr.probers.base import MediaProber
from boomarr.probers.ffprobe import FFProbeProber
from boomarr.state import InMemoryStateStore, StateStore
from boomarr.symlinks import SymlinkManager

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pipeline:
    """A fully configured pipeline of subsystems for processing libraries.

    Attributes:
        prober: The media prober to extract file metadata.
        filters: Ordered list of filters; all must pass (implicit AND).
        symlinks: The symlink manager for creating/removing links.
        state: The state store for tracking processed files.
    """

    prober: MediaProber
    filters: list[MediaFilter] = field(default_factory=list)
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

    def _default_prober(self) -> MediaProber:
        """Return the default prober chain.

        Currently FFprobe only.  Later this becomes a ``FallbackProber``
        that tries Radarr/Sonarr first and falls back to FFprobe.
        """
        return FFProbeProber()

    def _default_filters(self) -> list[MediaFilter]:
        """Return the default filter chain in evaluation order.

        1. FileExtensionFilter — fast, purely path-based, runs first to
           skip non-media files before the expensive probe step.
        2. AudioLanguageFilter — requires probed metadata.

        New filter types are added here.
        """
        return [
            FileExtensionFilter(),
            AudioLanguageFilter(),
        ]

    def for_scan(self) -> Pipeline:
        """Build a pipeline for the ``scan`` command.

        Full pipeline: probe → filter → symlink → clean stale → persist.
        """
        _LOGGER.debug("Building pipeline for 'scan'")
        return Pipeline(
            prober=self._default_prober(),
            filters=self._default_filters(),
            symlinks=SymlinkManager(),
            state=self._state,
        )

    def for_watch(self) -> Pipeline:
        """Build a pipeline for the ``watch`` command.

        Same as scan but will be used incrementally on filesystem events.
        """
        _LOGGER.debug("Building pipeline for 'watch'")
        return Pipeline(
            prober=self._default_prober(),
            filters=self._default_filters(),
            symlinks=SymlinkManager(),
            state=self._state,
        )

    def for_clean(self) -> Pipeline:
        """Build a pipeline for the ``clean`` command.

        Only needs the symlink manager — no probing or filtering.
        """
        _LOGGER.debug("Building pipeline for 'clean'")
        return Pipeline(
            prober=self._default_prober(),
            filters=[],
            symlinks=SymlinkManager(),
            state=self._state,
        )
