from app.services.activity_logger import webhook_activity_logger
from app.services.gundi import send_observations_to_gundi

from .configurations import DjiCloudApiWebhookConfig, DjiOsdFixPayload

TELEMETRY_FIELDS = (
    "height",
    "elevation",
    "gps",
    "horizontal_speed",
    "vertical_speed",
    "attitude_head",
    "mode_code",
    "battery",
)


@webhook_activity_logger()
async def webhook_handler(
    payload: DjiOsdFixPayload,
    integration=None,
    webhook_config: DjiCloudApiWebhookConfig = None,
):
    config = webhook_config or DjiCloudApiWebhookConfig()
    if config.source_name_prefix:
        source_name = f"{config.source_name_prefix}{payload.device_sn[-6:]}"
    else:
        source_name = payload.device_sn
    location = {"lat": payload.latitude, "lon": payload.longitude}
    if payload.elevation is not None:
        location["alt"] = payload.elevation
    observation = {
        "source": payload.device_sn,
        "source_name": source_name,
        "type": "tracking-device",
        "subject_type": config.subject_type,
        "recorded_at": payload.recorded_at.isoformat(),
        "location": location,
        "additional": {
            field: getattr(payload, field)
            for field in TELEMETRY_FIELDS
            if getattr(payload, field) is not None
        },
    }
    if payload.model_name:
        observation["additional"]["model_name"] = payload.model_name
    await send_observations_to_gundi(
        observations=[observation], integration_id=str(integration.id)
    )
    return {"observations_extracted": 1}
