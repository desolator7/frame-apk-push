# Per-title workaround for Lepton's APK extractor ignoring Chromium activity aliases.
# Bash reads BASH_ENV before running Lepton. Wait until Lepton has sourced its
# helpers, then provide the activity found in the original APK manifest.
_frame_set_activity() {
    if [[ "${SCRIPT_DIR:-}" == */Lepton ]] &&
       declare -F get_app_activity >/dev/null &&
       declare -F run_app_commands >/dev/null; then
        if [[ "${FRAME_APK_PUSH_ACTIVITY:-}" =~ ^[A-Za-z_][A-Za-z0-9_.$]*$ ]]; then
            export APP_ACTIVITY="${FRAME_APK_PUSH_ACTIVITY}"
        fi
        # Read while logd is alive. A dump during teardown can miss the crash
        # because Android has already stopped. Include child/GPU processes,
        # which Lepton's default main-PID filter excludes.
        if declare -F logcat_container >/dev/null; then
            local logcat_function
            logcat_function=$(declare -f logcat_container)
            eval "${logcat_function/logcat_container/_frame_original_logcat_container}"
            logcat_container() {
                if (( $# == 0 )); then
                    _frame_original_logcat_container --full -b all '*:W' \
                        'chromium:I' 'OpenXR-Loader:I' 'AndroidRuntime:E' \
                        'DEBUG:V' 'libc:W' 'ActivityManager:I' \
                        'LeptonProcessObserver:I'
                else
                    # Preserve Valve's separately filtered boot watchers.
                    _frame_original_logcat_container "$@"
                fi
            }
        fi
        # Lepton clears its saved Android buffers at every launch. Keep one
        # previous run for this Steam title so restarting after a crash does
        # not destroy the evidence. Never rotate another title's log directory.
        if declare -F logcat_debug_clear >/dev/null &&
           declare -F logcat_debug_dir >/dev/null; then
            local logcat_clear_function
            logcat_clear_function=$(declare -f logcat_debug_clear)
            eval "${logcat_clear_function/logcat_debug_clear/_frame_original_logcat_clear}"
            logcat_debug_clear() {
                local last_log_dir previous_log_dir
                last_log_dir=$(logcat_debug_dir)
                if [[ "${SteamAppId:-}" =~ ^[0-9]+$ ]] &&
                   [[ "$last_log_dir" == /*/lepton-logcats/steamlaunch-"$SteamAppId" ]] &&
                   [[ -d "$last_log_dir" ]]; then
                    previous_log_dir="${last_log_dir}.previous"
                    if ! { rm -rf -- "$previous_log_dir" &&
                           mkdir -p -- "$previous_log_dir" &&
                           cp -a -- "$last_log_dir/." "$previous_log_dir/"; }; then
                        echo 'Frame: Vorheriges Android-Absturzprotokoll konnte nicht gesichert werden.' >&2
                    fi
                fi
                _frame_original_logcat_clear "$@"
            }
        fi
        if declare -F setup_podman_mounts >/dev/null && [[ -n "${FRAME_APK_PUSH_DIRECTORY:-}" ]]; then
            _frame_shim_path="$FRAME_APK_PUSH_DIRECTORY/libframe-zygote.so"
            local mount_function
            mount_function=$(declare -f setup_podman_mounts)
            eval "${mount_function/setup_podman_mounts/_frame_original_mounts}"
            setup_podman_mounts() {
                _frame_original_mounts "$@"
                podman_mount_entry "$_frame_shim_path" /system/lib64/libframe-zygote.so ro,U
                podman_mount_entry "${_frame_shim_path%/*}/frame-services.jar" /system/framework/frame-services.jar ro,U
                podman_mount_entry "${_frame_shim_path%/*}/frame-before-start.sh" /system/bin/frame-before-start.sh ro,U
                podman_mount_entry "${_frame_shim_path%/*}/frame-webxr.js" /system/etc/frame-webxr.js ro,U
            }
        fi
        _frame_vr_permission="${FRAME_APK_PUSH_VR_PERMISSION:-allow}"
        _frame_xr_preparation="${FRAME_APK_PUSH_XR_PREPARATION:-auto}"
        case "$_frame_vr_permission" in
            allow|ask) ;;
            *) echo 'Ungültiger VR-Berechtigungsmodus.' >&2; exit 1 ;;
        esac
        case "$_frame_xr_preparation" in
            auto|off) ;;
            *) echo 'Ungültiger VR-Grafikvorbereitungsmodus.' >&2; exit 1 ;;
        esac
        # Start the shipped RestrictionsManager and prepare VR permissions.
        run_app_commands() {
            local app_id="${1:-$(get_app_id)}"
            local activity="${2:-$(get_app_activity)}"
            if [[ "$app_id" == org.chromium.chrome || "$app_id" == com.android.chrome ]]; then
                print "/system/bin/sh /system/bin/frame-before-start.sh ${app_id}/${activity} ${_frame_vr_permission} ${_frame_xr_preparation}"
            else
                print "am start -S ${app_id}/${activity}"
            fi
        }
        # Child Android/container setup shells must not inherit the hook.
        unset BASH_ENV FRAME_APK_PUSH_ACTIVITY FRAME_APK_PUSH_DIRECTORY FRAME_APK_PUSH_VR_PERMISSION FRAME_APK_PUSH_XR_PREPARATION
        _frame_activity_applied=true
    fi
    return 0
}
trap '_frame_set_activity; if [[ ${_frame_activity_applied:-false} == true ]]; then trap - DEBUG; unset -f _frame_set_activity; fi' DEBUG
