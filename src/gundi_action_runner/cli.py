"""gundi-runner: developer CLI for building and operating Gundi connectors."""
import asyncio
import os

import click
import pydantic

from gundi_action_runner import settings
from gundi_action_runner.services.action_runner import _portal
from gundi_action_runner.services.action_scheduler import CrontabSchedule
from gundi_action_runner.services.self_registration import register_integration_in_gundi


def _apply_handlers_setting(handlers):
    """Point discovery at the given handler modules for this process AND
    any child process (uvicorn --reload workers read the env var)."""
    if not handlers:
        return
    value = ",".join(handlers)
    os.environ["GUNDI_HANDLERS_MODULES"] = value
    settings.GUNDI_HANDLERS_MODULES = value


@click.group()
def cli():
    """Build, run, and register Gundi action-runner connectors."""


@cli.command()
@click.option("--handlers", "-m", multiple=True,
              help="Import path(s) of modules registering handlers with @action/@webhook. "
                   "Defaults to GUNDI_HANDLERS_MODULES or the legacy app.* convention.")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8080, show_default=True, type=int)
@click.option("--reload/--no-reload", default=True, show_default=True)
def run(handlers, host, port, reload):
    """Run the connector locally with uvicorn."""
    import uvicorn

    _apply_handlers_setting(handlers)
    uvicorn.run(
        "gundi_action_runner.app_factory:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@cli.command()
@click.option("--slug", default=None, help="Slug ID for the integration type")
@click.option("--name", default=None,
              help="Display name for the integration type (defaults to a name derived from the slug)")
@click.option("--service-url", default=None,
              help="Service URL used to trigger actions or receive webhooks")
@click.option("--handlers", "-m", multiple=True,
              help="Import path(s) of handler modules (defaults to env/legacy discovery)")
@click.option("--schedule", multiple=True,
              help='Schedules as "action_id:crontab" (e.g. "pull_events:0 */4 * * *")')
def register(slug, name, service_url, handlers, schedule):
    """Register this integration type (actions, schemas, schedules) in Gundi."""
    _apply_handlers_setting(handlers)
    schedules = {}
    for item in schedule:
        try:
            action_id, cron = item.split(":", 1)
            schedules[action_id.strip()] = CrontabSchedule.parse_obj_from_crontab(cron.strip())
        except (pydantic.ValidationError, ValueError) as e:
            raise click.BadParameter(
                f"Invalid schedule format: {item}.\n"
                f"Expected 'action_id:MIN HOUR DOM MON DOW [TZ]', "
                f"e.g. 'pull_events:0 */4 * * * -5'.\n{e}"
            )
    asyncio.run(
        register_integration_in_gundi(
            gundi_client=_portal,
            type_slug=slug,
            type_name=name,
            service_url=service_url,
            action_schedules=schedules,
        )
    )


DEFAULT_TEMPLATE = "gh:PADAS/gundi-integration-action-runner"


@cli.command()
@click.argument("destination", type=click.Path())
@click.option("--template", default=DEFAULT_TEMPLATE, show_default=True,
              help="Copier template source (git URL or local path)")
@click.option("--vcs-ref", default=None,
              help="Template git ref (tag/branch); defaults to the latest tag")
@click.option("--data", "data_pairs", multiple=True,
              help="Answer as KEY=VALUE (repeatable); unanswered questions prompt interactively")
@click.option("--defaults", is_flag=True, default=False,
              help="Fill unanswered questions with their defaults instead of prompting "
                   "(recommended for CI/scripted use; incomplete answers without this flag "
                   "in a non-TTY produce a broken scaffold — copier does not error)")
def new(destination, template, vcs_ref, data_pairs, defaults):
    """Scaffold a new connector project from the official template."""
    try:
        import copier
    except ImportError:
        raise click.UsageError(
            "copier is not installed. Install the CLI extras first:\n"
            "  pip install 'gundi-action-runner[cli]'"
        )
    data = {}
    for pair in data_pairs:
        key, _, value = pair.partition("=")
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        data[key] = value
    copier.run_copy(
        template, destination, data=data, vcs_ref=vcs_ref, defaults=defaults,
    )
    click.echo(
        f"\nProject created at {destination}. Next steps:\n"
        f"  cd {destination}\n"
        f"  pip install -e '.[dev]'\n"
        f"  pytest\n"
        f"  gundi-runner run --handlers <package>.handlers"
    )


if __name__ == "__main__":
    cli()
