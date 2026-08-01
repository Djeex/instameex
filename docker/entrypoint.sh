#!/bin/sh
set -e

CYAN="\033[1;36m"
NC="\033[0m"

VERSION=$(cat /app/VERSION)

echo -e "${CYAN}╭──────────────────────────────────────────────╮${NC}"
echo -e "${CYAN}│${NC}          Instam${CYAN}eex${NC} - Version ${VERSION}           ${CYAN}│${NC}"
echo -e "${CYAN}├──────────────────────────────────────────────┤${NC}"
echo -e "${CYAN}│${NC} Source: https://git.djeex.fr/Djeex/instameex ${CYAN}│${NC}"
echo -e "${CYAN}│${NC} Mirror: https://github.com/Djeex/instameex   ${CYAN}│${NC}"
echo -e "${CYAN}╰──────────────────────────────────────────────╯${NC}"

echo -e "[~] Checking required external tools..."
missing=""
for tool in ultrahdr_app exiftool; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    missing="$missing $tool"
  fi
done
if [ -n "$missing" ]; then
  echo -e "[!] Missing required tools:$missing"
  exit 1
fi
echo -e "[✓] Required tools found: ultrahdr_app, exiftool"

echo -e "[~] Starting Instameex web server..."
exec gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 120 main:app
