# Migrating an existing fork to the gundi-action-runner library

Forks of this template keep working without changes: merging upstream gives
you compatibility shims (`app/services/*` etc. re-export the library, with
`DeprecationWarning`s) and the framework rides in-tree under `src/` until you
migrate. Migration is optional and incremental.

## Step 0 — merge upstream (nothing else changes)

After merging, your CI/Dockerfile (inherited) run `pip install -e . --no-deps`
so `app.*` imports resolve to the library. Your handlers, configurations,
tests, and `uvicorn app.main:app` all keep working.

**What to expect during the merge:**

- **`app/conftest.py` will conflict** if you appended custom fixtures (most
  forks did). Resolution is mechanical: keep the upstream star-import line
  AND your custom fixtures below it.
- **Your `pytest` run now also collects upstream suites** (`tests/`,
  `examples/` via the inherited `pyproject.toml` testpaths). They pass in a
  fork context and pin the compatibility contract — treat failures there as
  signals, not noise. Trim `testpaths` if you must.
- **DeprecationWarnings** from `app.*` imports are expected — they mark the
  shim layer, which is removed after an announced window.

## Step 1 — adopt decorators in place (optional, incremental)

Decorate handlers inside your existing `app/actions/handlers.py`; the legacy
import fires the decorators, so decorated and `action_`-prefixed handlers can
coexist in that file:

```python
from gundi_action_runner import action

@action.pull(config=PullObservationsConfig, title="Pull Observations")
async def pull_observations(integration, action_config): ...   # was action_pull_observations
```

**Caution — moving handlers to a NEW module:** discovery via
`GUNDI_HANDLERS_MODULES` skips the legacy scan once ANY action is registered.
Don't split handlers across a new decorator module and a legacy module — move
them all at once, or keep decorating in place.

## Step 2 — cut over to the library layout

1. Point discovery at your module: set `GUNDI_HANDLERS_MODULES=myconnector.handlers`
   (or `app = create_app(handlers_modules=["myconnector.handlers"])` in `main.py`).
2. Change `app.*` imports to `gundi_action_runner.*` (mechanical
   find/replace; the shims made both names the same module objects).
3. Add `gundi-action-runner~=X.Y` to your requirements, delete the inherited
   `src/` tree and `app/` shims, keep only your connector code.

## Behavior changes to know about

- **Handler discovery is lazy.** The template scanned `app.actions.handlers`
  at import; the library populates on `create_app()` /
  `register_integration_in_gundi()` / first `execute_action()`. A broken
  import inside your handlers module now fails at first use instead of at
  process import — still loudly, just later.
- **Decorator ordering:** `@action.*`/`@webhook` must be the outermost
  decorator (see the [extension API](extension-api.md)).
- `python -m app.register` still works; `gundi-runner register` is its
  library-native replacement.
