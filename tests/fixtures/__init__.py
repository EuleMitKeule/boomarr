"""Fixture paths for Boomarr tests and development.

Media directory layout after running generate.py:

    media/
        movies/
            Sample.Movie.DE.mkv         - single German audio track
            Sample.Movie.EN.mkv         - single English audio track
            Sample.Movie.DE.EN.mkv      - German + English audio tracks
            Sample.Movie.DE.EN.FR.mkv   - German + English + French audio tracks
            Sample.Movie.NoAudio.mkv    - no audio tracks (video only)
        shows/
            Sample.Show/
                S01E01.DE.mkv           - German audio
                S01E02.EN.mkv           - English audio
                S01E03.DE.EN.mkv        - German + English audio
        non_media/
            poster.jpg                  - not a media container (extension filtered)
            info.nfo                    - XML sidecar, not a media container
            subtitle.en.srt             - subtitle file, not a media container

Language codes follow ISO 639-2 (deu, eng, fra) as returned by ffprobe.
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
MEDIA_DIR = FIXTURES_DIR / "media"
MOVIES_DIR = MEDIA_DIR / "movies"
SHOWS_DIR = MEDIA_DIR / "shows"
NON_MEDIA_DIR = MEDIA_DIR / "non_media"
