#!/system/bin/sh
set -eu
# Use the launcher's provider so it assigns the ID and refreshes its model.
# The baked home screen otherwise contains only Settings; the browser is in
# the app drawer, which is difficult to reach with the headset controls.
frame_launcher_query() {
    local result
    result=$(PARENT_UID=0 PARENT_GID=0 content query \
        --uri content://com.android.launcher3.settings/favorites \
        --projection _id --where "$1" 2>&1) || return 1
    case "$result" in
        Row:*|'No result found.') printf '%s\n' "$result" ;;
        *) printf '%s\n' "$result" >&2; return 1 ;;
    esac
}
frame_home_shortcut() {
    local component="$1" found slot title intent result
    case "$component" in
        *[!a-zA-Z0-9_./]*) return 1 ;;
    esac
    case "$component" in
        com.android.chrome/*) title=Chrome ;;
        org.chromium.chrome/*) title=Chromium ;;
        *) return 1 ;;
    esac
    found=$(frame_launcher_query "profileId=0 AND intent LIKE '%component=$component;%'") || return 1
    case "$found" in Row:*) return 0 ;; esac
    # Leave existing icons in place and use the first free hotseat position.
    for slot in 0 1 2 3; do
        found=$(frame_launcher_query "profileId=0 AND container=-101 AND (screen=$slot OR rank=$slot)") || return 1
        case "$found" in Row:*) continue ;; esac
        intent="#Intent;action=android.intent.action.MAIN;category=android.intent.category.LAUNCHER;launchFlags=0x10200000;component=$component;end"
        result=$(PARENT_UID=0 PARENT_GID=0 content insert \
            --uri content://com.android.launcher3.settings/favorites \
            --bind "title:s:$title" --bind "intent:s:$intent" \
            --bind container:i:-101 --bind "screen:i:$slot" --bind "rank:i:$slot" \
            --bind "cellX:i:$slot" --bind cellY:i:0 --bind spanX:i:1 --bind spanY:i:1 \
            --bind itemType:i:0 --bind profileId:i:0 2>&1) || return 1
        # Android's content command can report a provider error yet exit zero.
        if [ -n "$result" ]; then printf '%s\n' "$result" >&2; fi
        found=$(frame_launcher_query "profileId=0 AND intent LIKE '%component=$component;%'") || return 1
        case "$found" in Row:*) return 0 ;; esac
        return 1
    done
    return 1
}
frame_xr_preparation() {
    local mode="$1" package="$2" pid process_name started attempt
    pid=$(getprop frame.webxr.pid)
    process_name=''
    case "$pid" in
        ''|*[!0-9]*) pid='' ;;
        *) process_name=$(cat "/proc/$pid/comm" 2>/dev/null || true) ;;
    esac
    if [ "$process_name" = frame-webxr ] && kill -0 "$pid" 2>/dev/null; then
        if [ "$mode" = auto ] && [ "$(getprop frame.webxr.package)" = "$package" ]; then
            return 0
        fi
        kill "$pid"
        attempt=0
        while kill -0 "$pid" 2>/dev/null; do
            attempt=$((attempt + 1)); [ "$attempt" -lt 40 ] || return 1
            sleep 0.05
        done
    fi
    if [ "$mode" = off ]; then
        printf '%s\n' '{"version":1,"enabled":false,"connected":false,"phase":"disabled"}' >/data/local/tmp/frame-webxr.json
        return 0
    fi
    CLASSPATH=/system/framework/frame-services.jar PARENT_UID=0 PARENT_GID=0 \
        /system/bin/app_process /system/bin --nice-name=frame-webxr \
        FrameBrowserXR "$package" /system/etc/frame-webxr.js \
        >/data/local/tmp/frame-webxr.log 2>&1 &
    started=$!
    attempt=0
    # Wait for this helper before Chrome; it waits for the local browser socket.
    while [ "$(getprop frame.webxr.pid)" != "$started" ]; do
        attempt=$((attempt + 1))
        if [ "$attempt" -gt 40 ] || ! kill -0 "$started" 2>/dev/null; then
            cat /data/local/tmp/frame-webxr.log >&2
            kill "$started" 2>/dev/null || true
            return 1
        fi
        sleep 0.05
    done
}
if ! service check restrictions | grep -q ': found$'; then
    setprop frame.restrictions.ready 0
    CLASSPATH=/system/framework/frame-services.jar:/system/framework/services.jar \
        PARENT_UID=1000 PARENT_GID=1000 \
        /system/bin/app_process /system/bin FrameRestrictions \
        >/data/local/tmp/frame-restrictions.log 2>&1 &
    service_pid=$!
    attempt=0
    while [ "$(getprop frame.restrictions.ready)" != 1 ]; do
        attempt=$((attempt + 1))
        if [ "$attempt" -gt 40 ] || ! kill -0 "$service_pid" 2>/dev/null; then
            cat /data/local/tmp/frame-restrictions.log >&2
            echo 'Frame: RestrictionsManagerService konnte nicht gestartet werden.' >&2
            exit 1
        fi
        sleep 0.25
    done
fi
# Remove earlier experimental process/sandbox switches. User flags remain in Local State.
# Use the runtime's recommended resolution instead of its 16K maximum: Chromium
# rejects a side-by-side viewport whose total width equals its strict 16K limit.
echo '_ --webxr-max-framebuffer-scale=1' >/data/local/chrome-command-line
chmod 644 /data/local/chrome-command-line
# Stop before updating Preferences; a running browser would overwrite the change.
# This changes VR only. Site-specific blocks and other permissions stay intact.
am force-stop "${1%%/*}"
CLASSPATH=/system/framework/frame-services.jar PARENT_UID=0 PARENT_GID=0 \
    /system/bin/app_process /system/bin FrameBrowserPrefs "${1%%/*}" "${2:-allow}"
case "${3:-off}" in
    auto|off) ;;
    *) echo 'Frame: Ungültiger VR-Grafikvorbereitungsmodus.' >&2; exit 1 ;;
esac
if ! frame_xr_preparation "${3:-off}" "${1%%/*}"; then
    echo 'Frame: Automatische VR-Grafikvorbereitung konnte nicht gestartet werden. Browser startet ohne diesen Helfer.' >&2
fi
# A launcher without this provider must still be able to start the browser.
if ! frame_home_shortcut "$1"; then
    echo 'Frame: Browser-Verknüpfung konnte nicht ergänzt werden; Browser bleibt über die App-Liste erreichbar.' >&2
fi
am start -S "$1"
