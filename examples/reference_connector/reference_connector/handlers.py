from gundi_action_runner import action, webhook

from .configurations import (
    AuthConfig,
    PullObservationsConfig,
    ReferenceWebhookConfig,
    ReferenceWebhookPayload,
)


@action.auth(config=AuthConfig)
async def auth(integration, action_config):
    # A real connector validates credentials against the external API here
    # and returns {"valid_credentials": bool}.
    return {"valid_credentials": bool(action_config.api_key)}


@action.pull(config=PullObservationsConfig, title="Pull Reference Observations")
async def pull_observations(integration, action_config):
    # A real connector fetches from the external API, transforms the data, and
    # calls send_observations_to_gundi() here. Add @crontab_schedule(...) and
    # @activity_logger() from gundi_action_runner.services in a real connector.
    return {"observations_extracted": 0}


@webhook
async def webhook_handler(payload: ReferenceWebhookPayload, integration,
                          webhook_config: ReferenceWebhookConfig):
    # A real connector transforms the payload and forwards it to Gundi here.
    return {"data_points_qty": 1}
