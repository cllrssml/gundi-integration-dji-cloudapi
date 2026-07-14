#!/usr/bin/env python3
"""
DJI Pilot-to-Cloud OSD forwarder: self-hosted MQTT broker -> Gundi.

Subscribes to the reserve-hosted DJI Cloud API MQTT broker (see deploy/),
answers the DJI `update_topo` handshake, filters aircraft OSD from RC/gateway
OSD, carries incremental fields forward, and forwards one normalized fix per
position update to Gundi. One POST per fix.

Modes:
  (default)            live: connect to the broker and stream.
  --replay FILE        feed a captured *_capture.ndjson through the same logic.
  GUNDI_DRY=1 (env)    map + print the Gundi payloads but do NOT post.

Gundi output:
  GUNDI_API_KEY        apikey from your Gundi connection's Provider tab
  GUNDI_URL            https://sensors.api.gundiservice.org/v2/observations/ (default),
                       or the webhooks endpoint once the dji_cloudapi integration
                       type is available: https://hooks.gundiservice.org/webhooks
  GUNDI_MODE=sensors   sensors = ready-made Gundi observation (Sensors API v2 push);
                       webhook = normalized OSD-fix contract validated by the
                       gundi-integration-dji-cloudapi connector
  GUNDI_INTEGRATION_TYPE  optional; sent as x-gundi-integration-type header
                       (webhook mode, e.g. dji_cloudapi)
  GUNDI_SOURCE_SUFFIX  optional suffix appended to the serial (useful to provision
                       a separate test subject while another pipeline runs)
  GUNDI_SOURCE_NAME    subject display name (default "DJI {last 6 of serial}")
  GUNDI_MIN_INTERVAL=2 seconds; throttle posts per drone
  GUNDI_DRY=1          print Gundi payloads instead of posting

MQTT broker:
  MQTT_HOST=127.0.0.1 MQTT_PORT=1883 MQTT_TLS=0 MQTT_USERNAME MQTT_PASSWORD

Optional direct EarthRanger output (in addition to Gundi; both may run at once):
  ER_SITE, ER_TOKEN    EarthRanger sensors-push endpoint credentials
  PROVIDER=dji  SENSOR_TYPE=dji  SUBJECT_GROUP="DJI Drones"  MODEL_NAME
  SEND_SUBJECT_META=1  set 0 when feeding an existing subject
  DRY_RUN=1            print ER payloads instead of posting

Quality gates:
  MIN_GPS=1            min position_state.gps_number to treat a fix as valid
  POST_MIN_INTERVAL=0  seconds; throttle ER posts per drone (0 = every OSD, ~0.5Hz)
"""
import argparse
import json
import os
import ssl
import sys
import time
from datetime import datetime, timezone

import requests

ER_SITE = (os.environ.get("ER_SITE") or "").rstrip("/")
ER_TOKEN = os.environ.get("ER_TOKEN")
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
MQTT_TLS = os.environ.get("MQTT_TLS", "1" if MQTT_PORT == 8883 else "0") == "1"

PROVIDER = os.environ.get("PROVIDER", "dji")
SENSOR_TYPE = os.environ.get("SENSOR_TYPE", "dji")
SUBJECT_GROUP = os.environ.get("SUBJECT_GROUP", "DJI Drones")
MODEL_NAME = os.environ.get("MODEL_NAME", "DJI Mavic 3T")
SUBTYPE = os.environ.get("SUBTYPE", "drone")
DRONE_NAME = os.environ.get("DRONE_NAME")  # optional fixed name override
# When merged onto an existing subject, set SEND_SUBJECT_META=0 so pushes only add
# observations and never (re)assert subject name/subtype/group (which would recreate
# or rename the subject). Default 1 = normal auto-provisioning for a fresh drone.
SEND_SUBJECT_META = os.environ.get("SEND_SUBJECT_META", "1") == "1"
MIN_GPS = int(os.environ.get("MIN_GPS", "1"))
POST_MIN_INTERVAL = float(os.environ.get("POST_MIN_INTERVAL", "0"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

GUNDI_API_KEY = os.environ.get("GUNDI_API_KEY")
GUNDI_URL = os.environ.get("GUNDI_URL", "https://sensors.api.gundiservice.org/v2/observations/")
GUNDI_MODE = os.environ.get("GUNDI_MODE", "sensors")  # sensors | webhook
GUNDI_SOURCE_SUFFIX = os.environ.get("GUNDI_SOURCE_SUFFIX", "")
GUNDI_SOURCE_NAME = os.environ.get("GUNDI_SOURCE_NAME")
GUNDI_MIN_INTERVAL = float(os.environ.get("GUNDI_MIN_INTERVAL", "2"))
GUNDI_DRY = os.environ.get("GUNDI_DRY", "0") == "1"

STATUS_URL = f"{ER_SITE}/api/v1.0/sensors/{SENSOR_TYPE}/{PROVIDER}/status/"

session = requests.Session()
if ER_TOKEN:
    session.headers.update({"Authorization": f"Bearer {ER_TOKEN}", "Content-Type": "application/json"})

GUNDI_INTEGRATION_TYPE = os.environ.get("GUNDI_INTEGRATION_TYPE")

gundi_session = requests.Session()
if GUNDI_API_KEY:
    gundi_session.headers.update({"apikey": GUNDI_API_KEY, "Content-Type": "application/json"})
    if GUNDI_INTEGRATION_TYPE:
        gundi_session.headers.update({"x-gundi-integration-type": GUNDI_INTEGRATION_TYPE})

_state: dict[str, dict] = {}  # per-drone carry-forward (OSD is incremental)

# NOTE (Sam, by design): NO retirement. Unlike the ADS-B integration, this poster
# never marks a drone is_active=False. The drone Subject stays ACTIVE indefinitely,
# even between flights. Do not add an INACTIVE_TIMEOUT / retire_stale_subjects here.


def _recorded_at(message):
    ts = message.get("timestamp")
    if isinstance(ts, (int, float)) and ts > 1e11:  # epoch ms
        return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def push_status(sn, st, message):
    payload = {
        "manufacturer_id": sn,
        "source_type": "tracking-device",
        "model_name": MODEL_NAME,
        "recorded_at": _recorded_at(message),
        "location": {"lat": st["lat"], "lon": st["lon"]},  # ER sensor endpoint wants short keys
        "additional": _telemetry(st),
    }
    if SEND_SUBJECT_META:   # off when merged onto an existing subject
        payload["subject_name"] = DRONE_NAME or f"DJI {sn[-6:]}"
        payload["subject_subtype"] = SUBTYPE
        payload["subject_groups"] = [SUBJECT_GROUP]
    if DRY_RUN:
        print(f"  [DRY] {payload.get('subject_name', sn)} ({sn}) -> {payload['location']} "
              f"at {payload['recorded_at']} add={payload['additional']}")
        return True
    try:
        p = session.post(STATUS_URL, json=payload, timeout=10)
        if p.status_code in (200, 201):
            return True
        print(f"  push failed {sn}: {p.status_code} {p.text[:120]}")
    except Exception as e:
        print(f"  push error {sn}: {e}")
    return False


def _telemetry(st):
    return {k: st[k] for k in ("height", "elevation", "gps", "horizontal_speed",
                               "vertical_speed", "attitude_head", "mode_code", "battery")
            if st.get(k) is not None}


def push_gundi(sn, st, message):
    """Parallel Gundi output. Never raises into handle_osd; failures are logged only."""
    if GUNDI_MODE == "webhook":
        # Normalized OSD-fix contract for the gundi-integration-dji-cloudapi connector.
        body = {"device_sn": f"{sn}{GUNDI_SOURCE_SUFFIX}", "model_name": MODEL_NAME,
                "recorded_at": _recorded_at(message),
                "latitude": st["lat"], "longitude": st["lon"], **_telemetry(st)}
    else:
        # Ready-made observation for the Gundi Sensors API v2 (self-service push).
        body = {"source": f"{sn}{GUNDI_SOURCE_SUFFIX}",
                "source_name": GUNDI_SOURCE_NAME or f"DJI {sn[-6:]}",
                "subject_type": SUBTYPE, "type": "tracking-device",
                "recorded_at": _recorded_at(message),
                "location": {"lat": st["lat"], "lon": st["lon"]},
                "additional": _telemetry(st)}
    if GUNDI_DRY:
        print(f"  [GUNDI-DRY {GUNDI_MODE}] {body}")
        return
    try:
        r = gundi_session.post(GUNDI_URL, json=body, timeout=10)
        if r.status_code in (200, 201):
            st["gundi_posted"] = st.get("gundi_posted", 0) + 1
            n = st["gundi_posted"]
            if n <= 3 or n % 20 == 0:
                print(f"  gundi #{n} {sn} lat={st['lat']:.6f} lon={st['lon']:.6f} "
                      f"h={st.get('height')} gps={st.get('gps')}")
        else:
            print(f"  gundi push failed {sn}: {r.status_code} {r.text[:120]}")
    except Exception as e:
        print(f"  gundi push error {sn}: {e}")


def handle_osd(sn, message):
    data = message.get("data", message)
    st = _state.setdefault(sn, {})
    st["last_seen"] = time.time()
    if any(k in data for k in ("position_state", "attitude_head", "mode_code")):
        st["is_aircraft"] = True  # sticky; RC OSD lacks these
    if "latitude" in data:  st["lat"] = data["latitude"]
    if "longitude" in data: st["lon"] = data["longitude"]
    if "height" in data:    st["height"] = data["height"]
    if "elevation" in data: st["elevation"] = data["elevation"]
    for k in ("horizontal_speed", "vertical_speed", "attitude_head", "mode_code"):
        if k in data: st[k] = data[k]
    ps = data.get("position_state")
    if isinstance(ps, dict) and "gps_number" in ps:
        st["gps"] = ps["gps_number"]
    bat = data.get("battery")
    if isinstance(bat, dict) and "capacity_percent" in bat:
        st["battery"] = bat["capacity_percent"]

    if not st.get("is_aircraft"):
        return
    if not st.get("lat") or not st.get("lon"):      # 0/None = no fix
        return
    if (st.get("gps") or 0) < MIN_GPS:
        return
    now = time.time()
    if now - st.get("last_post", 0) < POST_MIN_INTERVAL:
        return
    st["last_post"] = now
    if (GUNDI_API_KEY or GUNDI_DRY) and now - st.get("last_gundi", 0) >= GUNDI_MIN_INTERVAL:
        st["last_gundi"] = now
        push_gundi(sn, st, message)
    if ((ER_SITE and ER_TOKEN) or DRY_RUN) and push_status(sn, st, message):
        st["posted"] = st.get("posted", 0) + 1
        if st["posted"] <= 3 or st["posted"] % 20 == 0:
            print(f"  #{st['posted']} {sn} lat={st['lat']:.6f} lon={st['lon']:.6f} "
                  f"h={st.get('height')} gps={st.get('gps')}")


def reply_topo(client, msg, message):
    resp = {"tid": message.get("tid"), "bid": message.get("bid"),
            "timestamp": int(time.time() * 1000), "data": {"result": 0}}
    client.publish(msg.topic + "_reply", payload=json.dumps(resp))


def run_replay(path):
    print(f"REPLAY {path}  (DRY_RUN={DRY_RUN})  -> {STATUS_URL if not DRY_RUN else 'stdout'}")
    for line in open(path):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("topic", "").endswith("/osd"):
            handle_osd(rec.get("device_sn") or rec["topic"].split("/")[2], rec.get("payload", rec))
    print("replay done. per-drone summary:")
    for sn, st in _state.items():
        print(f"  {sn}: aircraft={st.get('is_aircraft', False)} posted={st.get('posted', 0)} "
              f"last=({st.get('lat')},{st.get('lon')}) gps={st.get('gps')}")


def run_live():
    import paho.mqtt.client as mqtt

    def on_connect(client, userdata, flags, rc, properties=None):
        print(f"[connect] {MQTT_HOST}:{MQTT_PORT} rc={rc}")
        client.subscribe("sys/#", 0)
        client.subscribe("thing/#", 0)

    def on_message(client, userdata, msg):
        try:
            message = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        if msg.topic.endswith("status") and message.get("method") == "update_topo":
            reply_topo(client, msg, message)
            return
        if msg.topic.endswith("/osd"):
            handle_osd(msg.topic.split("/")[2], message)

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    if MQTT_TLS:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.on_connect = on_connect
    client.on_message = on_message
    print(f"DJI -> EarthRanger live. broker {MQTT_HOST}:{MQTT_PORT} tls={MQTT_TLS}  post->{STATUS_URL}")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", metavar="FILE", help="replay a captured ndjson instead of live MQTT")
    args = ap.parse_args()
    if not (GUNDI_API_KEY or GUNDI_DRY or (ER_SITE and ER_TOKEN) or DRY_RUN):
        sys.exit("Set GUNDI_API_KEY (or ER_SITE+ER_TOKEN, or GUNDI_DRY=1/DRY_RUN=1 to validate offline).")
    if args.replay:
        run_replay(args.replay)
    else:
        run_live()


if __name__ == "__main__":
    main()
