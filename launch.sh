#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
if [[ ! -x .venv/bin/python ]]; then
    command -v uv >/dev/null || {
        printf '%s\n' \
            'uv, SSH and rsync are required / uv, SSH und rsync werden benötigt:' \
            'Arch: sudo pacman -S uv openssh rsync' \
            'Debian: sudo apt install curl openssh-client rsync' \
            'Install uv on Debian / uv unter Debian installieren: curl -LsSf https://astral.sh/uv/install.sh | sh'
        exit 1
    }
    uv sync --extra test
fi
exec .venv/bin/python -m frame_apk_push.gui "$@"
