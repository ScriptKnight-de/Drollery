# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately instead:

- use the private vulnerability reporting / confidential issue feature of the site that hosts this repository, or
- contact the maintainer through the profile linked under *Settings › About* in the app.

Include what you found, how to reproduce it (a version number, the steps, and a sample request if you can) and what you
think the impact is. You will get an answer within about a week, and credit in the fix if you want it. There is no bug
bounty.

## Supported versions

Drollery is young (0.x). Only the latest release receives fixes.

## What Drollery is, and is not, built for

Drollery is a **self-hosted, single-owner** application. It protects the web interface and the HTTP API with an
account (scrypt-hashed password, optional two-factor authentication, login throttling) and per-device API keys. It is not
a multi-tenant service and does not try to isolate users from each other.

Known and documented trade-offs, which are not vulnerabilities by themselves:

- Anyone who holds a valid API key or session can make the server fetch URLs (`/api/v1/ingest`, "add a link"),
  including addresses on your own network. Revoke keys you no longer use.
- A **share link** is a capability URL: anyone who has it can open that single item until it expires or is revoked.
- Without HTTPS, passwords and keys travel unencrypted. Run it behind HTTPS if it leaves your LAN and set
  `DROLLERY_COOKIE_SECURE=1`.
- API keys of AI models and the TMDB/OMDb keys are stored in the database inside the data volume. Protect the volume,
  including backups, like a secret.

## In scope

Authentication or authorization bypass, injection (SQL, template, command), path traversal, stored/reflected script
injection, request forgery against the web interface, leaking a secret or another person's content, and bypassing the
limits on uploads and fetches.

## Hardening checklist for a public deployment

1. Put it behind a reverse proxy with HTTPS and set `DROLLERY_COOKIE_SECURE=1` and `DROLLERY_PUBLIC_URL`.
2. Choose your own setup code (`DROLLERY_SETUP_CODE`) or keep the generated one private, and create the admin right away.
3. Turn on two-factor authentication (*Settings › Security*).
4. Keep the data volume and its backups private.
5. Keep dependencies current (`docker compose build --pull`); `yt-dlp` in particular changes often.
