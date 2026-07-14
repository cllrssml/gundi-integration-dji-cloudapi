#!/usr/bin/env bash
# Runs ON the GCP VM. Installs Docker, points DuckDNS at this box, gets a
# Let's Encrypt cert, fills in the templates, and starts the platform.
#
# Provide these as environment variables before running (they are NOT stored
# in the repo — they live only here on the VM, in the running config):
#
#   export DOMAIN=yourreserve.duckdns.org      # your full DuckDNS hostname
#   export DUCKDNS_SUB=yourreserve             # just the subdomain part
#   export DUCKDNS_TOKEN=xxxxxxxx            # from your DuckDNS account
#   export DJI_APP_ID=123456                 # your Cloud API app (a number)
#   export DJI_APP_KEY=...                    # your Cloud API app key
#   export DJI_APP_LICENSE=...                # your Cloud API app license (from email)
#   export MQTT_USER=dji                      # broker user Pilot 2 will use
#   export MQTT_PASS=...                      # pick a strong random password
#
# Then:  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

for v in DOMAIN DUCKDNS_SUB DUCKDNS_TOKEN DJI_APP_ID DJI_APP_KEY DJI_APP_LICENSE MQTT_USER MQTT_PASS; do
  [ -n "${!v:-}" ] || { echo "Missing env var: $v"; exit 1; }
done

echo "== 1/6 Docker =="
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

echo "== 2/6 DuckDNS -> this VM (+ 5-min cron) =="
curl -fsS "https://www.duckdns.org/update?domains=${DUCKDNS_SUB}&token=${DUCKDNS_TOKEN}&ip=" ; echo
# Keep the hostname pointed at this VM every 5 min. Non-fatal: a missing/empty
# crontab must not abort the run (the immediate update above is what matters now).
CRON_LINE="*/5 * * * * curl -fsS 'https://www.duckdns.org/update?domains=${DUCKDNS_SUB}&token=${DUCKDNS_TOKEN}&ip='"
( ( crontab -l 2>/dev/null | grep -v 'duckdns.org' || true ); echo "$CRON_LINE" ) | crontab - || \
  echo "  (cron not installed; skipping auto-refresh — fine for the spike)"
echo "waiting for DNS to resolve to this host..."; sleep 20

echo "== 3/6 Let's Encrypt cert (certbot standalone on :80) =="
sudo docker run --rm -p 80:80 -v "$PWD/certs:/etc/letsencrypt" certbot/certbot \
  certonly --standalone -d "$DOMAIN" \
  --non-interactive --agree-tos --register-unsafely-without-email

echo "== 4/6 Fill templates (secrets stay on this VM only) =="
# The login page publicly embeds the broker credentials (required by the DJI
# JSBridge flow), so it is served from a secret random path only.
export LOGIN_SECRET="${LOGIN_SECRET:-$(openssl rand -hex 8)}"
cp login.html login.deployed.html
for f in login.deployed.html nginx.conf mosquitto.conf; do
  perl -pi -e 's/__DOMAIN__/$ENV{DOMAIN}/g;
               s/__DJI_APP_ID__/$ENV{DJI_APP_ID}/g;
               s/__DJI_APP_KEY__/$ENV{DJI_APP_KEY}/g;
               s/__DJI_APP_LICENSE__/$ENV{DJI_APP_LICENSE}/g;
               s/__MQTT_USER__/$ENV{MQTT_USER}/g;
               s/__MQTT_PASS__/$ENV{MQTT_PASS}/g;
               s/__LOGIN_SECRET__/$ENV{LOGIN_SECRET}/g' "$f"
done
# nginx mounts login.html by name -> use the filled copy
cp login.deployed.html login.html

echo "== 5/6 Mosquitto password file =="
mkdir -p mosquitto
sudo docker run --rm -v "$PWD/mosquitto:/m" eclipse-mosquitto:2 \
  mosquitto_passwd -b -c /m/passwd "$MQTT_USER" "$MQTT_PASS"

echo "== 6/6 Start platform =="
sudo docker compose up -d
sudo docker compose ps
echo
umask 077
echo "https://${DOMAIN}/login-${LOGIN_SECRET}" > ~/login-url.txt
echo "DONE. In DJI Pilot 2 -> Cloud Service -> Open Platforms, enter the URL"
echo "saved to ~/login-url.txt (kept out of this output on purpose):"
echo "   cat ~/login-url.txt"
echo "Then tap Login. Capture OSD on this VM with:"
echo "   MQTT_HOST=127.0.0.1 MQTT_PORT=1883 MQTT_TLS=0 MQTT_USERNAME=${MQTT_USER} MQTT_PASSWORD=*** python3 ../capture_osd.py"
