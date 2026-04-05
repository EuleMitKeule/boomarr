"""Media filtering subsystem.

Defines the abstract interface for filtering media files and provides
built-in filter implementations (file extensions, audio language).
"""

from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.base import MediaFilter
from boomarr.filters.file_extension import FileExtensionFilter

__all__ = ["AudioLanguageFilter", "FileExtensionFilter", "MediaFilter"]
