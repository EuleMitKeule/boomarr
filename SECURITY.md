# Security Policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please **do not** open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/EuleMitKeule/boomarr/security/advisories/new)
instead. You will get a response within a few days.

## Security model

- Boomarr needs read access to your media and write access only to its
  config directory and the output directories. It refuses to run when a
  source directory is writable (in watch mode: it keeps running but refuses
  to scan).
- The Docker image drops root privileges (`PUID`/`PGID`) or runs fully
  rootless (`--user`), and the Helm chart uses a read-only root filesystem
  without capabilities.
- The web UI requires a login by default (Argon2id password hash, signed
  `HttpOnly`/`SameSite` session cookies, login throttling, CSRF header check,
  strict Content-Security-Policy). Single sign-on via OpenID Connect
  (authorization code + PKCE, ID token signature and claims verified) and
  forward-auth behind trusted proxies are supported. See
  [Web UI & security](docs/web-ui.md#security-notes).
- The first admin account can only be created from a private network or with
  the one-time setup token printed in the log.
- Secrets in `boomarr.yml` are never sent to the browser; `auth.json` is
  stored with mode `0600`.
- Webhooks and scripts authenticate with an API key (generated on first
  start). `/health` is public; `/metrics` is public unless `metrics_auth`
  is enabled.
