#!/usr/bin/env bash
# Update ewbot to the latest code of the branch and restart both bots.  Usage: sudo bash deploy/update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ewbot}"
BRANCH="${BRANCH:-claude/elliott-wave-trading-bot-36grv4}"
EWBOT_USER="${EWBOT_USER:-ubuntu}"
INSTANCES="${INSTANCES:-ewbot-15m ewbot-30m}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausfuehren: sudo bash $0" >&2
  exit 1
fi
git config --global --add safe.directory "$APP_DIR" || true
git -C "$APP_DIR" fetch --prune origin "$BRANCH"
git -C "$APP_DIR" checkout "$BRANCH"
git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
sed "s/^User=.*/User=$EWBOT_USER/" "$APP_DIR/deploy/ewbot@.service" > /etc/systemd/system/ewbot@.service
chown -R "$EWBOT_USER":"$EWBOT_USER" "$APP_DIR"
systemctl daemon-reload
for inst in $INSTANCES; do
  systemctl restart "ewbot@$inst"
  systemctl --no-pager --lines=5 status "ewbot@$inst" || true
done
echo "Update fertig. Log: journalctl -u ewbot@ewbot-15m -f"
