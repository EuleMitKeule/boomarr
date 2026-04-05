"""Abstract base class for media filters."""

import abc

from boomarr.config import LibraryConfig
from boomarr.models import MediaInfo


class MediaFilter(abc.ABC):
    """Decides whether a media file should be included in the filtered library.

    Filters are applied sequentially. All filters must pass for a file to
    be included (implicit AND). New filter types are added by subclassing.
    """

    @abc.abstractmethod
    def matches(self, info: MediaInfo, library: LibraryConfig) -> bool:
        """Return True if the media file passes this filter."""
