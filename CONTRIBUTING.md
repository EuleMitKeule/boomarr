# Contributing

Thanks for your interest in Boomarr!

## Setup

```bash
git clone https://github.com/EuleMitKeule/boomarr && cd boomarr
uv sync --all-groups
```

`ffprobe` (package `ffmpeg`) is needed for the integration test; it is
skipped automatically when missing.

## Checks

Every pull request must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict .
uv run pytest
```

CI additionally builds the Docker image and runs a smoke test against the
fixture media, and lints the Helm chart.

## Guidelines

- **Safety first.** Boomarr runs unattended against people's media. Any code
  that deletes something must only ever touch symlinks it owns, and must be
  covered by tests (including "share not mounted" situations).
- **Backwards compatibility.** Existing configs must keep working and output
  folder names must not change. Config changes need docs in
  `docs/configuration.md` and, for new options, in `config.example.yml`
  (keep `boomarr/config.example.yml` identical; a test enforces this).
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `chore:` …). Releases and changelogs are
  generated from them by semantic-release.

## Project layout

```
boomarr/
  __main__.py      CLI (typer)
  config.py        pydantic config models, loading, validation
  pipeline.py      builds subsystems per command
  processor.py     discovery, probing, reconciliation of one library
  state.py         probe cache (SQLite / memory)
  symlinks.py      symlink creation/removal
  languages.py     ISO 639 normalisation
  filters/         pre-/post-probe filters
  probers/         ffprobe
  triggers/        schedule, webhook
  watcher.py       watch-mode event loop
charts/boomarr/    Helm chart
contrib/           Unraid template, systemd unit
```
