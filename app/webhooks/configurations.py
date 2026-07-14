from datetime import datetime
from typing import Optional

import pydantic

from .core import WebhookConfiguration, WebhookPayload


class DjiOsdFixPayload(WebhookPayload):
    """
    One normalized DJI Cloud API OSD fix, as forwarded by the reserve-side bridge.

    The bridge (see reserve-side/) subscribes to the self-hosted DJI Cloud API MQTT
    broker, filters aircraft OSD from RC/gateway OSD, carries incremental fields
    forward, and POSTs one of these per fix. Identity, position, and time are
    required; telemetry fields are optional and omitted when unknown.
    """
    device_sn: str = pydantic.Field(
        ..., description="Aircraft serial number; used as the Gundi source id."
    )
    recorded_at: datetime = pydantic.Field(
        ..., description="Fix timestamp, ISO 8601 (UTC)."
    )
    latitude: float = pydantic.Field(..., ge=-90.0, le=90.0)
    longitude: float = pydantic.Field(..., ge=-180.0, le=180.0)
    model_name: Optional[str] = pydantic.Field(
        None, description="Aircraft model, e.g. 'DJI Mavic 3T'."
    )
    height: Optional[float] = pydantic.Field(
        None, description="Height above the takeoff point, meters."
    )
    elevation: Optional[float] = pydantic.Field(
        None, description="Elevation above sea level, meters."
    )
    gps: Optional[int] = pydantic.Field(
        None, description="GPS satellite count (position_state.gps_number)."
    )
    horizontal_speed: Optional[float] = pydantic.Field(
        None, description="Horizontal speed, m/s."
    )
    vertical_speed: Optional[float] = pydantic.Field(
        None, description="Vertical speed, m/s."
    )
    attitude_head: Optional[float] = pydantic.Field(
        None, description="Heading, degrees."
    )
    mode_code: Optional[int] = pydantic.Field(
        None, description="DJI flight mode code."
    )
    battery: Optional[int] = pydantic.Field(
        None, description="Battery capacity, percent."
    )


class DjiCloudApiWebhookConfig(WebhookConfiguration):
    subject_type: str = pydantic.Field(
        "drone", description="Subject type for provisioned subjects."
    )
    source_name_prefix: Optional[str] = pydantic.Field(
        None,
        description=(
            "Optional display-name prefix; the subject is named "
            "'{prefix}{last 6 chars of the serial}' (e.g. 'DJI ' -> 'DJI 00A1B2'). "
            "When unset, the full serial is used as the source name."
        ),
    )
