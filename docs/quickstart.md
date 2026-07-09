# Quickstart: build a Gundi connector with gundi-action-runner

## Install

```bash
pip install "gundi-action-runner[cli]"
```

## Scaffold a project

```bash
gundi-runner new my-connector
# answer the prompts (project name, slug, pull/webhook support)
cd my-connector
pip install -e ".[dev]"
pytest
```

For CI or scripted use, pass `--defaults` (plus `--data KEY=VALUE` overrides) — without it, incomplete answers in a non-interactive shell produce a broken scaffold because copier fills nothing and does not error.

The generated project contains:

| Path | Purpose |
|---|---|
| `<package>/handlers.py` | Your action/webhook handlers (`@action.*`, `@webhook`) |
| `<package>/configurations.py` | Pydantic config models rendered in the Gundi portal |
| `<package>/client.py` | HTTP client for the external API |
| `<package>/transformers.py` | Raw data → Gundi observations/events |
| `main.py` | `app = create_app(handlers_modules=[...])` |
| `tests/` | Example tests using the built-in pytest fixtures |

## Run locally

```bash
gundi-runner run --handlers <package>.handlers
# API docs at http://127.0.0.1:8080/docs
```

## Add another action

```bash
gundi-runner add-action   # --type and --id prompt interactively; pass --title/--crontab to set them (they default to empty)
```

## Register in Gundi

```bash
export GUNDI_API_BASE_URL=... KEYCLOAK_CLIENT_ID=... KEYCLOAK_CLIENT_SECRET=...
gundi-runner register --slug my_connector --name "My Connector" \
  --handlers <package>.handlers --schedule "pull_observations:0 */4 * * *"
```

## Keep the scaffold fresh

Generated projects record the template source; pull scaffold improvements with
`copier update` (framework updates come via `pip install -U gundi-action-runner`).

Next: [extension API reference](extension-api.md) ·
[migrating an existing fork](fork-migration.md)
