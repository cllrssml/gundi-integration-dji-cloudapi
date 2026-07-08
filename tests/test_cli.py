"""gundi-runner CLI: run + register (new/add-action tested in their own tasks)."""
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from gundi_action_runner.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_group_lists_commands(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "register"):
        assert command in result.output


def test_run_invokes_uvicorn_with_factory(runner, mocker, monkeypatch):
    monkeypatch.delenv("GUNDI_HANDLERS_MODULES", raising=False)
    uvicorn_run = mocker.patch("uvicorn.run")
    result = runner.invoke(
        cli, ["run", "--handlers", "myconn.handlers", "--port", "9000"]
    )
    assert result.exit_code == 0, result.output
    args, kwargs = uvicorn_run.call_args
    assert args[0] == "gundi_action_runner.app_factory:create_app"
    assert kwargs["factory"] is True
    assert kwargs["port"] == 9000
    # The reload subprocess reads env; the in-process factory reads settings
    import os

    from gundi_action_runner import settings

    assert os.environ["GUNDI_HANDLERS_MODULES"] == "myconn.handlers"
    assert settings.GUNDI_HANDLERS_MODULES == "myconn.handlers"


def test_register_forwards_options(runner, mocker):
    register = mocker.patch(
        "gundi_action_runner.cli.register_integration_in_gundi", new_callable=AsyncMock
    )
    result = runner.invoke(
        cli,
        [
            "register",
            "--slug", "x_tracker",
            "--name", "X Tracker",
            "--service-url", "https://x.example.com",
            "--schedule", "pull_observations:0 */4 * * *",
        ],
    )
    assert result.exit_code == 0, result.output
    kwargs = register.call_args.kwargs
    assert kwargs["type_slug"] == "x_tracker"
    assert kwargs["type_name"] == "X Tracker"
    assert kwargs["service_url"] == "https://x.example.com"
    assert "pull_observations" in kwargs["action_schedules"]


def test_register_rejects_bad_schedule(runner, mocker):
    mocker.patch(
        "gundi_action_runner.cli.register_integration_in_gundi", new_callable=AsyncMock
    )
    result = runner.invoke(cli, ["register", "--schedule", "not-a-schedule"])
    assert result.exit_code != 0
    assert "Invalid schedule format" in result.output
