# Contributing to Valo

Thank you for helping. Bug reports, translations, device support, extensions and code are all welcome.

## Before you start

- For a bug, open an issue with the version, what you did, what you expected and logs
  (`docker compose logs <service>`). Remove passwords and tokens from logs.
- For a bigger change, open an issue first to agree on the approach.
- Security problems go privately, see SECURITY.md.

## Development setup

You need Docker with the compose plugin, Python 3.14 with [uv](https://docs.astral.sh/uv/) and Node.js 22.

```
./valo demo up        # demo home with simulated devices, http://localhost:3000, mikko / valo-demo
./valo real up        # live environment with a Zigbee stick, http://localhost:3100
```

Each environment is a separate compose project with its own volumes and its file `envs/<env>.env`,
created from `envs/<env>.env.example` with random secrets on the first run.

## Checks

Run all of them before a pull request:

```
cd backend && uv run ruff format --check src tests && uv run ruff check src tests && uv run lint-imports
cd backend && ./scripts/test.sh
cd mocks && uv run ruff check valo_mocks tests && uv run python -m unittest discover -s tests
cd web && npm run build
cd web && npm run e2e      # against a running demo
```

## Code rules

- Python: type hints everywhere, ruff with line length 120, layers `server | ws | mqtt | ext | agent | cameras`
  over `domain` over `db` over `lib` are checked by import-linter
- API errors are `ApplicationError(code, status, **params)` with texts in `backend/src/app/locales/errors.json`
- side effects after a database commit go through `db.after(s, fn)`
- device data is untrusted, parse it through `ingest.parse`
- database changes: edit the models, then create a new Atlas migration, applied migrations are never edited
- interface texts exist in all seven languages, add them with `web/scripts/i18n-add.py`
- user facing changes come with documentation in `docs/<lang>/` (ru, uk, en)
- no stubs or TODOs in production code, do not log passwords, tokens or camera stream addresses

## Extensions

New integrations usually belong in an extension, not in the core. Start from
[valo-home/extension-template](https://github.com/valo-home/extension-template) and read the developer
guide in Valo, Documentation, For developers.

## License

By contributing you agree that your contribution is licensed under the Apache License 2.0.
