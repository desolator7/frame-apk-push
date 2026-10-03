#!/usr/bin/env bash
set -euo pipefail
frame_app_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
lepton_entry="${HOME}/.local/share/Steam/steamapps/common/Lepton/lepton"
if [[ ! -x "$lepton_entry" ]]; then
    echo 'Lepton ist nicht installiert.' >&2
    exit 1
fi
export STEAM_COMPAT_INSTALL_PATH="$frame_app_dir"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_COMPAT_CLIENT_INSTALL_PATH:-${HOME}/.local/share/Steam}"
export STEAM_COMPAT_DATA_PATH="${STEAM_COMPAT_DATA_PATH:-${STEAM_COMPAT_CLIENT_INSTALL_PATH}/steamapps/compatdata/${SteamAppId:-frame_chromium}}"
export STEAM_COMPAT_SHADER_PATH="${STEAM_COMPAT_SHADER_PATH:-${STEAM_COMPAT_CLIENT_INSTALL_PATH}/steamapps/shadercache/${SteamAppId:-frame_chromium}}"
mkdir -p -- "$STEAM_COMPAT_DATA_PATH" "$STEAM_COMPAT_SHADER_PATH"
export BASH_ENV="$frame_app_dir/frame-lepton-activity.sh"
mapfile -t frame_launch_config < "$frame_app_dir/launcher-activity.txt"
export FRAME_APK_PUSH_ACTIVITY="${frame_launch_config[0]}"
export FRAME_APK_PUSH_VR_PERMISSION="${frame_launch_config[1]:-allow}"
export FRAME_APK_PUSH_XR_PREPARATION="${frame_launch_config[2]:-auto}"
case "$FRAME_APK_PUSH_VR_PERMISSION" in
    allow|ask) ;;
    *) echo 'Ungültiger VR-Berechtigungsmodus.' >&2; exit 1 ;;
esac
case "$FRAME_APK_PUSH_XR_PREPARATION" in
    auto|off) ;;
    *) echo 'Ungültiger VR-Grafikvorbereitungsmodus.' >&2; exit 1 ;;
esac
export FRAME_APK_PUSH_DIRECTORY="$frame_app_dir"
export LEPTON_ENV_LD_PRELOAD=/system/lib64/libframe-zygote.so
# Keep Android crash/system buffers when the title exits, including later VR
# startup failures that Lepton's default 30-second capture would miss.
export LEPTON_DUMP_LOGCAT=1
exec "$lepton_entry" waitforexitandrun -- "$frame_app_dir/ChromePublic.apk"
