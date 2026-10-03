#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
command -v uv >/dev/null || {
    printf '%s\n' \
        'uv, SSH and rsync are required / uv, SSH und rsync werden benötigt:' \
        'Arch: sudo pacman -S uv openssh rsync' \
        'Debian: sudo apt install curl openssh-client rsync' \
        'Install uv on Debian / uv unter Debian installieren: curl -LsSf https://astral.sh/uv/install.sh | sh'
    exit 1
}
uv sync --locked --extra test
.venv/bin/python - <<'PY'
from pathlib import Path
import os
root = Path.cwd()
data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
def escape(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
entry = data / 'applications/frame-apk-push.desktop'
entry.parent.mkdir(parents=True, exist_ok=True)
entry.write_text(f'''[Desktop Entry]
Type=Application
Name=Frame APK Push
Comment=Set up Android browsers and WebXR on Steam Frame / Android-Browser und WebXR auf Steam Frame einrichten
Exec="{escape(root / 'launch.sh')}"
Icon={root / 'assets/frame-apk-push.svg'}
Terminal=false
Categories=Network;
StartupNotify=true
''')
entry.chmod(0o755)
print('Menu entry installed / Menüeintrag installiert:', entry)
PY
