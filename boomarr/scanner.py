"""Media library scanner module.

Handles scanning and discovery of media files across Plex and Jellyfin libraries.
Provides functionality to identify media entries and extract metadata including
audio track information for filtering operations.
"""

import logging

_LOGGER = logging.getLogger(__name__)
