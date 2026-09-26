# Contributing

Thanks for your interest in Boomarr!

## Setup

```bash
git clone https://github.com/EuleMitKeule/boomarr && cd boomarr
uv sync --all-groups
```

`ffprobe` (package `ffmpeg`) is needed for the integration test; it is
skipped automatically when missing.

The web UI lives in `frontend/` (React, TypeScript, Vite, Tailwind CSS,
TanStack Query). Node.js 22+ is required:

```bash
cd frontend
npm ci
npm run dev      # http://localhost:5173, proxies /api to `boomarr watch` on :9797
npm run build    # writes boomarr/web/dist, which `boomarr watch` serves
```

## Checks

Every pull request must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --cov=boomarr    # fails below 100 % line + branch coverage
(cd frontend && npm run typecheck && npm test && npm run build)
```

CI additionally builds the Docker image and runs a smoke test against the
fixture media, and lints the Helm chart.

## Guidelines

- **100 % test coverage.** Line and branch coverage of `boomarr/` is
  enforced in CI; new code needs tests (prefer real behaviour over mocks).
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
  triggers/        schedule trigger
  daemon.py        `watch`: scan queue, triggers, web server, config reloads
  config_store.py  reads/validates/writes boomarr.yml for the web UI
  auth_store.py    admin account, API key, session secret (auth.json)
  health.py        health checks and scan preflight
  events.py        live events (SSE) and in-memory log buffer
  web/             FastAPI app: REST API, auth (sessions, OIDC), security
frontend/          web UI (built into boomarr/web/dist)
charts/boomarr/    Helm chart
contrib/           Unraid template, systemd unit
```
