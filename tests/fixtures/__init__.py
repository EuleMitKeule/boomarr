"""Fixture paths for Boomarr tests and development.

Media directory layout after running generate.py:

    media/
        movies/
            Sample.Movie.DE.mkv             - single German audio track
            Sample.Movie.EN.mkv             - single English audio track
            Sample.Movie.DE.EN.mkv          - German + English audio tracks
            Sample.Movie.DE.EN.FR.mkv       - German + English + French audio tracks
            Sample.Movie.NoAudio.mkv        - no audio tracks (video only)
            Movie.In.Folder/
                Movie.In.Folder.DE.EN.mkv   - German + English audio
                poster.jpg                  - non-media sidecar
                movie.nfo                   - non-media sidecar
            Collection/
                Sequel/
                    Sequel.Movie.DE.mkv     - German audio
                    Sequel.Movie.DE.srt     - non-media sidecar
        shows/
            Sample.Show/
                Season 1/
                    S01E01.DE.mkv           - German audio
                    S01E02.EN.mkv           - English audio
                    S01E03.DE.EN.mkv        - German + English audio
                    banner.jpg              - non-media sidecar
                Season 2/
                    S02E01.DE.EN.mkv        - German + English audio
                    S02E02.EN.mkv           - English audio
                    S02E03.DE.mkv           - German audio
                    show.nfo                - non-media sidecar
            Another.Show/
                Season 1/
                    S01E01.DE.EN.FR.mkv     - German + English + French audio
                    poster.jpg              - non-media sidecar
        non_media/
            poster.jpg                      - not a media container (extension filtered)
            info.nfo                        - XML sidecar, not a media container
            subtitle.en.srt                 - subtitle file, not a media container

Language codes follow ISO 639-2 (deu, eng, fra) as returned by ffprobe.
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
MEDIA_DIR = FIXTURES_DIR / "media"
MOVIES_DIR = MEDIA_DIR / "movies"
SHOWS_DIR = MEDIA_DIR / "shows"
NON_MEDIA_DIR = MEDIA_DIR / "non_media"
