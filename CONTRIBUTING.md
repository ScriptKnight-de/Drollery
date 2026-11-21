# Contributing to Drollery

Thanks for your interest! Bug reports, ideas and pull requests are welcome.

## Set up

The steps to run it from source and to run the tests are in [docs/development.md](docs/development.md).

## Before you send a change

- **Tests:** add or update tests for what you change, and keep the whole suite green. Tests use invented data only.
- **Translations:** every user-visible string goes through `t("…")` (Python) or `_("…")` (templates) and needs an entry
  in `src/drollery/locales/de.py`. `python scripts/i18n_scan.py` lists what is missing; the tests fail otherwise.
- **No secrets and no personal content.** Never commit API keys, tokens, passwords, real e-mail addresses, private
  addresses, your own media or your own library's titles. `tests/test_hygiene.py` checks the project for these and for
  unused imports and stale translations; fix what it reports instead of silencing it.
- **Keep it small and plain:** one logical change per commit, conventional commit messages (`feat:`, `fix:`, `docs:`,
  `chore:`), and no new dependency unless it is clearly worth it.
- **Look at it in a browser** if you change the interface, in the light and the dark theme and on a narrow screen.

## Reporting bugs

Please include the version (*Settings › About*), what you did, what you expected and what happened, and any error from
`docker compose logs drollery`. **Security problems go through [SECURITY.md](SECURITY.md), not the public tracker.**

## Adding a language

See "Translating" in [docs/development.md](docs/development.md). English is the source text, so a new language is one file plus one line in
`i18n.LOCALES` and a flag in `templates/flags/`.

## License

By contributing you agree that your contribution is released under the project's [MIT License](LICENSE).
