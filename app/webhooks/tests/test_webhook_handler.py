import json
import os

import pydantic
import pytest

from app.webhooks.configurations import DjiCloudApiWebhookConfig, DjiOsdFixPayload
from app.webhooks.handlers import webhook_handler

FIXES_FILE = os.path.join(os.path.dirname(__file__), "files", "osd_fixes.json")


@pytest.fixture
def osd_fixes():
    with open(FIXES_FILE) as f:
        return json.load(f)


@pytest.fixture
def mock_send_observations_to_gundi(mocker):
    mock = mocker.AsyncMock(return_value={"object_id": "0000", "created_at": "2026-07-12T10:10:48Z"})
    mocker.patch("app.webhooks.handlers.send_observations_to_gundi", mock)
    return mock


@pytest.fixture
def mock_publish_event(mocker):
    mock = mocker.AsyncMock()
    mocker.patch("app.services.activity_logger.publish_event", mock)
    return mock


@pytest.mark.asyncio
async def test_full_fix_maps_to_observation(
    osd_fixes, integration_v2_with_webhook, mock_send_observations_to_gundi, mock_publish_event
):
    payload = DjiOsdFixPayload.parse_obj(osd_fixes[0])

    result = await webhook_handler(
        payload=payload,
        integration=integration_v2_with_webhook,
        webhook_config=DjiCloudApiWebhookConfig(),
    )

    assert result == {"observations_extracted": 1}
    mock_send_observations_to_gundi.assert_called_once()
    kwargs = mock_send_observations_to_gundi.call_args.kwargs
    assert kwargs["integration_id"] == str(integration_v2_with_webhook.id)
    (observation,) = kwargs["observations"]
    assert observation["source"] == "MOCK5F1DJ34T000000A1"
    assert observation["source_name"] == "MOCK5F1DJ34T000000A1"
    assert observation["type"] == "tracking-device"
    assert observation["subject_type"] == "drone"
    assert observation["location"] == {
        "lat": osd_fixes[0]["latitude"],
        "lon": osd_fixes[0]["longitude"],
        "alt": osd_fixes[0]["elevation"],
    }
    assert observation["additional"]["gps"] == 14
    assert observation["additional"]["battery"] == 95
    assert observation["additional"]["model_name"] == "DJI Mavic 3T"
    assert "latitude" not in observation["additional"]


@pytest.mark.asyncio
async def test_minimal_fix_maps_without_telemetry(
    integration_v2_with_webhook, mock_send_observations_to_gundi, mock_publish_event
):
    payload = DjiOsdFixPayload.parse_obj(
        {
            "device_sn": "MOCK5F1DJ34T000000A1",
            "recorded_at": "2026-07-12T10:10:48+00:00",
            "latitude": -21.4012,
            "longitude": 28.3403,
        }
    )

    result = await webhook_handler(
        payload=payload,
        integration=integration_v2_with_webhook,
        webhook_config=DjiCloudApiWebhookConfig(),
    )

    assert result == {"observations_extracted": 1}
    (observation,) = mock_send_observations_to_gundi.call_args.kwargs["observations"]
    assert observation["additional"] == {}
    assert "alt" not in observation["location"]


@pytest.mark.asyncio
async def test_config_overrides_subject_type_and_name(
    osd_fixes, integration_v2_with_webhook, mock_send_observations_to_gundi, mock_publish_event
):
    payload = DjiOsdFixPayload.parse_obj(osd_fixes[2])
    config = DjiCloudApiWebhookConfig(subject_type="uav", source_name_prefix="DJI ")

    await webhook_handler(
        payload=payload,
        integration=integration_v2_with_webhook,
        webhook_config=config,
    )

    (observation,) = mock_send_observations_to_gundi.call_args.kwargs["observations"]
    assert observation["subject_type"] == "uav"
    assert observation["source_name"] == "DJI 0000A1"
    assert observation["location"]["alt"] == pytest.approx(355.2)


def test_missing_position_is_rejected():
    with pytest.raises(pydantic.ValidationError):
        DjiOsdFixPayload.parse_obj(
            {"device_sn": "MOCK5F1DJ34T000000A1", "recorded_at": "2026-07-12T10:10:48+00:00"}
        )


def test_out_of_range_position_is_rejected():
    with pytest.raises(pydantic.ValidationError):
        DjiOsdFixPayload.parse_obj(
            {
                "device_sn": "MOCK5F1DJ34T000000A1",
                "recorded_at": "2026-07-12T10:10:48+00:00",
                "latitude": -91.0,
                "longitude": 28.34,
            }
        )


@pytest.mark.asyncio
async def test_every_captured_fix_produces_one_observation(
    osd_fixes, integration_v2_with_webhook, mock_send_observations_to_gundi, mock_publish_event
):
    for fix in osd_fixes:
        await webhook_handler(
            payload=DjiOsdFixPayload.parse_obj(fix),
            integration=integration_v2_with_webhook,
            webhook_config=DjiCloudApiWebhookConfig(source_name_prefix="DJI "),
        )

    assert mock_send_observations_to_gundi.call_count == len(osd_fixes)
