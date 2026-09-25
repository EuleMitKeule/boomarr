"""Abstract base classes for media filters.

Two categories of filters exist:

* **Pre-probe filters** — cheap, path-based checks that run *before* the
  expensive probe step.  They decide whether a file should be probed at all.
* **Post-probe filters** — metadata-aware checks that run *after* probing.
  They decide which symlink libraries a file belongs to and each contributes
  a suffix used for automatic output directory naming.
"""

import abc
from pathlib import Path

from boomarr.models import MediaInfo


class PreProbeFilter(abc.ABC):
    """Filter applied before probing.  Only has access to the file path.

    Pre-probe filters are cheap, path-based checks used to skip files
    before the expensive probe step.
    """

    @abc.abstractmethod
    def matches(self, file_path: Path) -> bool:
        """Return True if the file should be probed."""


class PostProbeFilter(abc.ABC):
    """Filter applied after probing, with access to full media metadata.

    Post-probe filters determine which symlink libraries a file belongs to.
    Each filter contributes a suffix for automatic output directory naming.
    """

    def __init__(self, *, suffix: str | None = None, invert: bool = False) -> None:
        self._custom_suffix = suffix
        self._invert = invert

    def matches(self, info: MediaInfo) -> bool:
        """Return True if the media file passes this filter (honours ``invert``)."""
        result = self.evaluate(info)
        return not result if self._invert else result

    @abc.abstractmethod
    def evaluate(self, info: MediaInfo) -> bool:
        """Return True if the media file satisfies the (non-inverted) condition."""

    @abc.abstractmethod
    def default_suffix(self) -> str:
        """Return the default suffix for this filter's configuration."""

    @property
    def suffix(self) -> str:
        """Return the suffix (custom override or default)."""
        if self._custom_suffix is not None:
            return self._custom_suffix
        base = self.default_suffix()
        return f"not-{base}" if self._invert else base
