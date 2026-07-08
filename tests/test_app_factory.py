import sys
import types

import pytest
from fastapi.testclient import TestClient

from gundi_action_runner import create_app
from gundi_action_runner.registry import registry


@pytest.fixture(autouse=True)
def clean_registry():
    saved_actions = dict(registry.action_handlers)
    saved_webhook = registry.webhook_handler
    registry.reset()
    yield registry
    registry.reset()
    registry.action_handlers.update(saved_actions)
    registry.webhook_handler = saved_webhook


@pytest.fixture
def decorated_module():
    from gundi_action_runner.actions.core import PullActionConfiguration
    from gundi_action_runner.decorators import action

    module = types.ModuleType("fake_decorated_handlers")

    def _register():
        @action.pull(config=PullActionConfiguration, id="pull_stuff")
        async def pull_stuff(integration, action_config):
            return {}

    module.register = _register
    sys.modules["fake_decorated_handlers"] = module
    # Registration happens when create_app imports the module; emulate
    # decorator-at-import by registering on first import via module-level call.
    _register()
    yield "fake_decorated_handlers"
    del sys.modules["fake_decorated_handlers"]


def test_create_app_builds_routes():
    app = create_app(handlers_modules=[])
    paths = {route.path for route in app.routes}
    assert "/" in paths
    assert "/push-data" in paths
    assert any(path.startswith("/v1/actions") for path in paths)
    assert any(path.startswith("/webhooks") for path in paths)


def test_health_endpoint():
    app = create_app(handlers_modules=[])
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_actions_endpoint_lists_registered_actions(decorated_module):
    app = create_app(handlers_modules=[])  # registry already populated by fixture
    client = TestClient(app)
    response = client.get("/v1/actions/")
    assert response.status_code == 200
    assert "pull_stuff" in response.json()


def test_create_app_scans_legacy_module_when_registry_empty(monkeypatch):
    from gundi_action_runner.actions.core import PullActionConfiguration

    module = types.ModuleType("fake_legacy_for_factory")

    async def action_pull_legacy(integration, action_config: PullActionConfiguration):
        return {}

    module.action_pull_legacy = action_pull_legacy
    sys.modules["fake_legacy_for_factory"] = module
    monkeypatch.setattr(
        "gundi_action_runner.settings.GUNDI_LEGACY_ACTIONS_MODULE", "fake_legacy_for_factory"
    )
    try:
        create_app()
        assert "pull_legacy" in registry.action_handlers
    finally:
        del sys.modules["fake_legacy_for_factory"]
