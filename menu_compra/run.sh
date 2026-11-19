#!/bin/sh
set -eu

export MENU_COMPRA_DATA_DIR="${MENU_COMPRA_DATA_DIR:-/data}"

# No confiar en X-Forwarded-For: el backend comprueba la IP real del Supervisor.
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8099 --no-proxy-headers
