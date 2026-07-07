# Design: `gundi-action-runner` — the template as a published library

**Date:** 2026-07-07
**Status:** Approved (brainstorming session)
**Repo:** PADAS/gundi-integration-action-runner

## Problem

This repo is a template for building Gundi Action Runners. Today, developers fork it and edit
`app/actions/handlers.py`, `app/actions/configurations.py`, `app/webhooks/handlers.py`, etc.
Framework updates reach connectors only by merging from upstream, which every fork must do
independently. Forking is not always suitable — especially for third-party developers.

**Goal:** publish the framework as a versioned pip package (`gundi-action-runner`) with a clean
extension API, guided scaffolding, and documentation, while keeping this repo mergeable for
existing forks during a transition window.

## Decisions made

| Question | Decision |
|---|---|
| Consumption model | Layered: library (extension API) + CLI (scaffold via copier, interactive `add-action`) |
| Existing fork migration | Eventual, not day 1 — clean break to ship, but keep migration mechanical |
| Extension API | Decorator registry (`@action.pull(config=...)`) |
| Repo strategy | Monorepo: published library + reference connector + fork-compat shims, in this repo |
| v0.1 scope | Actions (auth/pull/push), webhooks, re-export shims, copier template + `add-action` CLI |

## Section 1 — Repo & package layout (monorepo)

```
gundi-integration-action-runner/
├── src/gundi_action_runner/        # THE PUBLISHED LIBRARY (PyPI: gundi-action-runner)
│   ├── __init__.py                 # exports: create_app, action, webhook, crontab_schedule, settings
│   ├── registry.py                 # decorator registry (replaces name-prefix scanning)
│   ├── app_factory.py              # create_app()
│   ├── settings.py                 # env-driven framework settings
│   ├── actions/core.py             # base config classes (Auth/Pull/Push/Generic/Internal, ExecutableActionMixin)
│   ├── webhooks/core.py            # WebhookPayload, JQ/Dynamic/Hex configs
│   ├── routers/{actions,webhooks,config_events}.py
│   ├── services/{action_runner,gundi,state,activity_logger,config_manager,
│   │             action_scheduler,self_registration,config_events_consumer,errors,utils}.py
│   ├── testing/                    # public pytest plugin (see Section 5)
│   └── cli.py                      # gundi-runner: run | new | add-action | register
├── app/                            # REFERENCE CONNECTOR + fork-compat shims (NOT published)
│   ├── services/*.py               # thin re-export shims → gundi_action_runner.services.*
│   ├── actions/{core}.py           # shim
│   ├── actions/{handlers,configurations}.py   # decorator-based example (the "copy me" code)
│   ├── webhooks/*.py               # shims + example
│   ├── settings/__init__.py        # shim → gundi_action_runner.settings
│   ├── main.py                     # shim → create_app()
│   └── conftest.py                 # shim → gundi_action_runner.testing fixtures
├── template/                       # copier template used by `gundi-runner new`
├── tests/                          # library's own test suite (moved from app/services/tests/)
├── pyproject.toml                  # builds gundi_action_runner; app/ excluded from the dist
└── docs/
```

- The published artifact is `gundi_action_runner` (src layout).
- `app/` is what forks merge from — it carries both a working decorator-based example and the
  compat shims, so an upstream merge keeps existing forks running unchanged.

## Section 2 — Extension API & app composition

Decorators populate a module-level registry instead of scanning for `action_`-prefixed names:

```python
from gundi_action_runner import action, webhook, crontab_schedule
from myconnector.configurations import PullObsConfig, AuthConfig, PushConfig

@action.auth(config=AuthConfig)
async def auth(integration, action_config): ...

@crontab_schedule("*/15 * * * *")
@action.pull(config=PullObsConfig, title="Fetch Collar Positions")
async def pull_observations(integration, action_config): ...

@action.push(config=PushConfig)   # push validates data/metadata params, as today
async def push_events(integration, action_config, data: MyData, metadata): ...

@webhook(config=GenericJsonTransformConfig)   # one webhook handler per connector, as today
async def webhook_handler(payload, webhook_config): ...
```

- **Titles** (PR #77 parity): display-name override is a decorator parameter (`title=...`).
  The registry also sets the `action_title` and `crontab_schedule` **function attributes**, so
  legacy introspection code (`getattr(func, "action_title", ...)`) and the legacy-module
  adoption path keep working. The standalone `action_title()` decorator remains importable from
  the shim layer.
- **Composition:** `create_app()` imports the configured handler module(s) so decorators fire,
  then builds the FastAPI app (routers, lifespan/self-registration, CORS, exception handlers)
  from the registry:

  ```python
  # myconnector/main.py  (and the reference app/main.py shim)
  from gundi_action_runner import create_app
  app = create_app()   # handler module from GUNDI_HANDLERS_MODULE env or pyproject config
  ```

- **Legacy adoption:** `create_app()` can also scan a legacy module for `action_`-prefixed
  functions with annotation-based config discovery (today's convention). A fork migrates by
  adding the dependency and pointing at its existing `handlers.py` — no handler rewrites day 1.
- **Registry validation is fail-fast at import time** with actionable messages naming the
  file/function: duplicate action ids; pull/auth handlers missing the
  `(integration, action_config)` signature; push handlers missing annotated `data` or
  `metadata` params; more than one `@webhook` handler.

## Section 3 — Settings

- Keep the **env-driven** model (12-factor deploys unchanged). Framework settings live in
  `gundi_action_runner.settings`; `app/settings/__init__.py` becomes a re-export shim so
  `import app.settings` keeps resolving for forks.
- Connector-side settings (`INTEGRATION_TYPE_SLUG`, `INTEGRATION_TYPE_NAME`,
  `INTEGRATION_SERVICE_URL`) remain env-driven and can also be passed to `create_app()`.
- **Dependency posture:** the library launches on modern pins — `fastapi>=0.110`,
  `httpx>=0.28`, `gundi-client-v2 3.x` — folding in the `FIX_TESTCLIENT_PLAN.md` bumps from the
  start so the TestClient breakage never enters the package.
- **Open dependency decision:** pydantic v1 vs v2 is resolved by whatever `gundi-client-v2 3.x`
  requires; verify during implementation (affects `UISchemaModelMixin`, `schema_json()`,
  `DyntamicFactory`).

## Section 4 — CLI & scaffolding (`gundi-runner`)

One console-script entry point with four subcommands:

- **`new`** — wraps **copier** with `template/`. Prompts: connector name, type slug, display
  name, which action types to include. Generates: `pyproject.toml` (depends on
  `gundi-action-runner~=X.Y`), `{package}/{handlers,configurations,client,transformers}.py`,
  `main.py`, `Dockerfile`, `.env.example`, example tests. Copier chosen over cookiecutter
  because `copier update` lets generated projects pull template improvements later — a soft
  replacement for fork-merge.
- **`add-action`** — interactive codegen: prompts for action type + id + title (+ crontab for
  pull); appends a stub handler to `handlers.py` and a config class to `configurations.py`.
  Pure text generation against the project's files; refuses politely if expected files are
  missing rather than guessing.
- **`run`** — dev server: import handler module → `create_app()` → uvicorn with reload.
- **`register`** — replaces `python -m app.register`; `--slug/--name/--service-url/--schedule`
  at parity with today's `register.py` (including `--name` from PR #77).

CLI deps (`click`, `copier`) live in an optional extra: `pip install gundi-action-runner[cli]`,
so deployed containers don't carry scaffolding tooling.

## Section 5 — Testing

1. **Library's own tests** move to `tests/` at repo root, importing from
   `gundi_action_runner`. The existing suite carries over nearly wholesale (code moves, not
   rewritten).
2. **Public pytest plugin** — `gundi_action_runner.testing`, declared via
   `[project.entry-points.pytest11]`. Today's ~1000-line `app/conftest.py` (mock integrations,
   Gundi clients, pubsub mocks) becomes public fixtures connector authors get for free
   (`mock_gundi_client`, `integration_v2`, `mock_publish_event`, ...). Scaffolded projects
   include example tests using them. This is the biggest net-new piece beyond extraction.
3. **Reference connector tests** stay under `app/` and run in CI against the in-repo library —
   they double as integration tests of the public API. A CI job imports every legacy `app.*`
   path and asserts it resolves, keeping the shims honest.

## Section 6 — Versioning, releases, and fork migration

- **Publishing:** semver, `0.x` while the API settles. Git tags → GitHub Actions → PyPI
  (trusted publishing). src layout ensures tests run against the built package.
- **Shim lifecycle:** shims are one-liners (`from gundi_action_runner.services.gundi import *`
  plus explicit re-exports for non-underscore names) and emit `DeprecationWarning` on import.
  They live in the repo's `app/`, not the published package — forks get them by merging
  upstream as today. Removal after an announced window (e.g. two minor releases after v1.0).
- **Fork migration path** (documented as a guide; enabled day 1, not pushed):
  1. Add `gundi-action-runner` to requirements; merge upstream to get shims → everything runs.
  2. Optionally adopt decorators at leisure.
  3. Point `create_app()`/`GUNDI_HANDLERS_MODULE` at their handlers module and delete inherited
     framework files.
  The legacy-module scanner means step 1 requires zero handler rewrites.

## Out of scope (this design)

- Migrating any existing fork (guide only).
- The local web-UI dev tooling in `local/web-ui/`.
- Changes to Gundi platform APIs or the portal.

## Implementation phases (suggested ordering for the plan)

1. Extract library to `src/gundi_action_runner/` with registry + `create_app()`; move tests.
2. Fold in dependency bumps (`FIX_TESTCLIENT_PLAN.md`); resolve pydantic question.
3. Shims in `app/` + reference connector converted to decorator API; shim-resolution CI job.
4. Public pytest plugin (`gundi_action_runner.testing`).
5. Packaging + release automation (PyPI trusted publishing).
6. Copier template + `gundi-runner new` / `run` / `register`.
7. `gundi-runner add-action` interactive codegen.
8. Docs: quickstart, extension API reference, fork migration guide.
