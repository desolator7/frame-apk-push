#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
command -v uv >/dev/null || { echo 'Bitte zuerst installieren: sudo pacman -S uv'; exit 1; }
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
Comment=Chromium und WebXR auf Steam Frame einrichten
Exec="{escape(root / 'launch.sh')}"
Icon={root / 'assets/frame-apk-push.svg'}
Terminal=false
Categories=Network;
StartupNotify=true
''')
entry.chmod(0o755)
print('Menüeintrag installiert:', entry)
PY
