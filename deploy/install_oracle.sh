#!/usr/bin/env bash
# ewbot installer for Oracle Cloud Free Tier (Ubuntu 22.04 / 24.04, ARM aarch64 or x86_64).
# Idempotent: running it again updates the code and restarts the bots.
#
#   curl -fsSL https://raw.githubusercontent.com/maehrsteuern/scalp-bot-mt4/claude/elliott-wave-trading-bot-36grv4/deploy/install_oracle.sh | sudo bash
#
# Overridable: REPO_URL, BRANCH, APP_DIR, EWBOT_USER, INSTANCES="ewbot-15m ewbot-30m"
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/maehrsteuern/scalp-bot-mt4.git}"
BRANCH="${BRANCH:-claude/elliott-wave-trading-bot-36grv4}"
APP_DIR="${APP_DIR:-/opt/ewbot}"
EWBOT_USER="${EWBOT_USER:-ubuntu}"
INSTANCES="${INSTANCES:-ewbot-15m ewbot-30m}"

log() { printf '\n==> %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausfuehren: sudo bash $0" >&2
  exit 1
fi
if ! id "$EWBOT_USER" >/dev/null 2>&1; then
  echo "Benutzer '$EWBOT_USER' existiert nicht. Mit EWBOT_USER=<name> erneut starten." >&2
  exit 1
fi
echo "Architektur: $(uname -m), System: $(. /etc/os-release && echo "$PRETTY_NAME")"

log "Pakete installieren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git ca-certificates curl

# ewbot needs Python >= 3.11 (Ubuntu 22.04 ships 3.10 -> install python3.11 from the archive)
PY=python3
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  log "Python 3.11 installieren (System-Python ist zu alt)"
  apt-get install -y python3.11 python3.11-venv
  PY=python3.11
fi

log "Code nach $APP_DIR holen ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  git config --global --add safe.directory "$APP_DIR" || true
  git -C "$APP_DIR" fetch --prune origin "$BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

log "Python-Umgebung (.venv) einrichten"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  "$PY" -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

log ".env anlegen (falls noch nicht vorhanden)"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/config/.env.example" "$APP_DIR/.env"
  echo "Neu angelegt: $APP_DIR/.env  (bitte spaeter ausfuellen)"
else
  echo "Vorhanden, bleibt unveraendert: $APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
mkdir -p "$APP_DIR/state" "$APP_DIR/logs" "$APP_DIR/data" "$APP_DIR/reports"
chown -R "$EWBOT_USER":"$EWBOT_USER" "$APP_DIR"

log "systemd-Dienst installieren"
sed "s/^User=.*/User=$EWBOT_USER/" "$APP_DIR/deploy/ewbot@.service" > /etc/systemd/system/ewbot@.service
systemctl daemon-reload
for inst in $INSTANCES; do
  systemctl enable "ewbot@$inst"
  systemctl restart "ewbot@$inst"
done

log "Fertig"
for inst in $INSTANCES; do
  systemctl --no-pager --lines=0 status "ewbot@$inst" || true
done
cat <<HINTS

Naechste Schritte:
  1. API-Keys / Telegram eintragen:   sudo nano $APP_DIR/.env
  2. Pruefen:                         cd $APP_DIR && sudo -u $EWBOT_USER .venv/bin/python -m ewbot check --config config/ewbot-15m.yaml
  3. Neu starten:                     sudo systemctl restart ewbot@ewbot-15m ewbot@ewbot-30m
  Status:                             systemctl status ewbot@ewbot-15m
  Live-Log:                           journalctl -u ewbot@ewbot-15m -f
                                      journalctl -u ewbot@ewbot-30m -f
  Update spaeter:                     sudo bash $APP_DIR/deploy/update.sh
HINTS
