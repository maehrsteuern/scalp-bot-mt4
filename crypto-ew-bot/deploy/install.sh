#!/usr/bin/env bash
# Run as the bot user inside crypto-ew-bot/. Sets up venv + config. Does not touch system files.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install requests pyyaml pytest
[ -f config.yaml ] || cp config.example.yaml config.yaml
if [ ! -f .env ]; then
  printf '# nur fuer Live noetig (API-Key mit Recht "Handeln", OHNE Auszahlung)\nCDC_API_KEY=\nCDC_API_SECRET=\n' > .env
fi
chmod 600 .env
mkdir -p state logs out
python -m pytest -q || { echo "Tests fehlgeschlagen - nicht weiter einrichten"; exit 1; }
echo "Fertig. Naechster Schritt (als root): siehe VPS_SETUP.md, Abschnitt 5."
