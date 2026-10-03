#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
if [[ ! -x .venv/bin/python ]]; then
    command -v uv >/dev/null || { echo 'Bitte uv installieren: sudo pacman -S uv'; exit 1; }
    uv sync --extra test
fi
exec .venv/bin/python -m frame_apk_push.gui "$@"
