"""Media probing subsystem.

Defines the abstract interface for extracting audio/video metadata from media
files and provides the default FFprobe-based implementation.
"""

from boomarr.probers.base import MediaProber
from boomarr.probers.ffprobe import FFProbeProber

__all__ = ["FFProbeProber", "MediaProber"]
