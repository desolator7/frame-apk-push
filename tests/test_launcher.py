import os
from pathlib import Path
import subprocess
import sys
import pytest
from lxml import etree
from frame_apk_push.core import launcher_activity, ROOT


def test_chromium_activity_alias_is_selected_instead_of_xr_host():
    manifest = etree.fromstring(b'''<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application>
    <activity android:name="org.chromium.components.webxr.XrHostActivity"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="org.khronos.openxr.intent.category.IMMERSIVE_HMD"/></intent-filter></activity>
    <activity-alias android:name="com.google.android.apps.chrome.Main" android:targetActivity="org.chromium.chrome.browser.ChromeTabbedActivity"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity-alias>
    </application></manifest>''')
    assert launcher_activity(manifest, 'org.chromium.chrome') == 'com.google.android.apps.chrome.Main'


@pytest.mark.parametrize('mode', ['allow', 'ask'])
@pytest.mark.parametrize('package', ['org.chromium.chrome', 'com.android.chrome'])
@pytest.mark.parametrize('xr_mode', ['auto', 'off'])
def test_lepton_hook_runs_after_library_reset_and_does_not_leak_to_children(tmp_path, mode, package, xr_mode):
    lepton = tmp_path / 'Lepton'
    lepton.mkdir()
    (lepton / 'library.sh').write_text('''APP_ACTIVITY=""
get_app_activity() { :; }
run_app_commands() { :; }
setup_podman_mounts() { printf 'original mounts\\n'; }
podman_mount_entry() { printf 'mount|%s|%s|%s\\n' "$1" "$2" "$3"; }
''')
    script = lepton / 'lepton'
    script.write_text('''#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(dirname "$0")
source "$SCRIPT_DIR/library.sh"
printf '%s\\n' "$APP_ACTIVITY"
[[ ! -v BASH_ENV ]]
[[ ! -v FRAME_APK_PUSH_ACTIVITY ]]
[[ ! -v FRAME_APK_PUSH_DIRECTORY ]]
[[ ! -v FRAME_APK_PUSH_VR_PERMISSION ]]
[[ ! -v FRAME_APK_PUSH_XR_PREPARATION ]]
[[ -z "$(trap -p DEBUG)" ]]
print() { printf '%s' "$*"; }
run_app_commands "$EXPECTED_PACKAGE" "$APP_ACTIVITY"
printf '\\n'
setup_podman_mounts
''')
    env = {**os.environ, 'BASH_ENV': str(ROOT / 'assets/lepton-activity.sh'),
           'FRAME_APK_PUSH_ACTIVITY': 'com.google.android.apps.chrome.Main',
           'FRAME_APK_PUSH_VR_PERMISSION': mode,
           'FRAME_APK_PUSH_XR_PREPARATION': xr_mode,
           'EXPECTED_PACKAGE': package,
           'FRAME_APK_PUSH_DIRECTORY': str(tmp_path / 'Title With Spaces')}
    result = subprocess.run(['bash', str(script)], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == 'com.google.android.apps.chrome.Main'
    command = result.stdout.splitlines()[1]
    assert command == f'/system/bin/sh /system/bin/frame-before-start.sh {package}/com.google.android.apps.chrome.Main {mode} {xr_mode}'
    assert result.stdout.splitlines()[2:] == [
        'original mounts',
        f'mount|{tmp_path}/Title With Spaces/libframe-zygote.so|/system/lib64/libframe-zygote.so|ro,U',
        f'mount|{tmp_path}/Title With Spaces/frame-services.jar|/system/framework/frame-services.jar|ro,U',
        f'mount|{tmp_path}/Title With Spaces/frame-before-start.sh|/system/bin/frame-before-start.sh|ro,U',
        f'mount|{tmp_path}/Title With Spaces/frame-webxr.js|/system/etc/frame-webxr.js|ro,U']


@pytest.mark.parametrize('mode', ['allow', 'ask'])
@pytest.mark.parametrize('xr_mode', ['auto', 'off', None])
def test_native_launcher_provides_required_steam_paths(tmp_path, mode, xr_mode):
    app = tmp_path / 'app'
    app.mkdir()
    launcher = app / 'launch-chromium.sh'
    launcher.write_bytes((ROOT / 'assets/launch-chromium.sh').read_bytes())
    (app / 'launcher-activity.txt').write_text('com.google.android.apps.chrome.Main\n' + mode + '\n' +
                                             (xr_mode + '\n' if xr_mode else ''))
    lepton = tmp_path / '.local/share/Steam/steamapps/common/Lepton/lepton'
    lepton.parent.mkdir(parents=True)
    lepton.write_text('''#!/bin/bash
set -eu
[[ -d "$STEAM_COMPAT_DATA_PATH" ]]
[[ -d "$STEAM_COMPAT_SHADER_PATH" ]]
[[ "$STEAM_COMPAT_INSTALL_PATH" == "$EXPECTED_APP" ]]
[[ "$FRAME_APK_PUSH_ACTIVITY" == com.google.android.apps.chrome.Main ]]
[[ "$FRAME_APK_PUSH_VR_PERMISSION" == "$EXPECTED_MODE" ]]
[[ "$FRAME_APK_PUSH_XR_PREPARATION" == "$EXPECTED_XR_MODE" ]]
[[ "$BASH_ENV" == "$EXPECTED_APP/frame-lepton-activity.sh" ]]
[[ "$LEPTON_ENV_LD_PRELOAD" == /system/lib64/libframe-zygote.so ]]
[[ "$LEPTON_DUMP_LOGCAT" == 1 ]]
printf '%s\\n' "$@"
''')
    lepton.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith('STEAM_COMPAT_') and k != 'BASH_ENV'}
    env.update(HOME=str(tmp_path), EXPECTED_APP=str(app), EXPECTED_MODE=mode, EXPECTED_XR_MODE=xr_mode or 'auto')
    result = subprocess.run(['bash', str(launcher)], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['waitforexitandrun', '--', str(app / 'ChromePublic.apk')]


@pytest.mark.parametrize('matching_title', [True, False])
def test_crash_logs_survive_restart_only_for_the_own_title(tmp_path, matching_title):
    lepton = tmp_path / 'Lepton'
    lepton.mkdir()
    context = '3825586637' if matching_title else '1234'
    logs = tmp_path / 'logs/lepton-logcats' / ('steamlaunch-' + context)
    logs.mkdir(parents=True)
    (logs / 'logcat-crash.log').write_text('native crash evidence\n')
    (logs / 'logcat-system.log').write_text('process death evidence\n')
    previous = Path(str(logs) + '.previous')
    previous.mkdir()
    (previous / 'stale.log').write_text('older run\n')
    (lepton / 'library.sh').write_text('''
get_app_activity() { :; }
run_app_commands() { :; }
logcat_debug_dir() { printf '%s' "$LOGS"; }
logcat_debug_clear() { rm -rf -- "$LOGS"; }
''')
    script = lepton / 'lepton'
    script.write_text('''#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(dirname "$0")
source "$SCRIPT_DIR/library.sh"
logcat_debug_clear
''')
    env = {**os.environ, 'BASH_ENV': str(ROOT / 'assets/lepton-activity.sh'),
           'SteamAppId': '3825586637', 'LOGS': str(logs)}
    result = subprocess.run(['bash', str(script)], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert not logs.exists()
    if matching_title:
        assert (previous / 'logcat-crash.log').read_text() == 'native crash evidence\n'
        assert (previous / 'logcat-system.log').read_text() == 'process death evidence\n'
        assert not (previous / 'stale.log').exists()
    else:
        assert list(previous.iterdir()) == [previous / 'stale.log']


@pytest.mark.parametrize('watcher_arguments', ['', 'steamlaunch-3825586637'])
def test_live_crash_capture_includes_child_processes_and_preserves_boot_watchers(tmp_path, watcher_arguments):
    lepton = tmp_path / 'Lepton'
    lepton.mkdir()
    (lepton / 'library.sh').write_text('''
get_app_activity() { :; }
run_app_commands() { :; }
logcat_container() { printf '%s\\n' "$@"; }
''')
    script = lepton / 'lepton'
    script.write_text('''#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(dirname "$0")
source "$SCRIPT_DIR/library.sh"
logcat_container "$@"
''')
    env = {**os.environ, 'BASH_ENV': str(ROOT / 'assets/lepton-activity.sh')}
    result = subprocess.run(['bash', str(script), *([watcher_arguments] if watcher_arguments else [])],
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    arguments = result.stdout.splitlines()
    if watcher_arguments:
        assert arguments == [watcher_arguments]
        return
    assert arguments[:3] == ['--full', '-b', 'all']
    assert 'DEBUG:V' in arguments and 'chromium:I' in arguments
    assert not any(argument.startswith('--pid') for argument in arguments)


@pytest.mark.parametrize('failed', [False, True])
def test_preferences_are_updated_after_stop_and_failure_prevents_browser_start(tmp_path, failed):
    tools = tmp_path / 'bin'
    tools.mkdir()
    trace = tmp_path / 'trace'
    for name, content in {
        'service': '#!/bin/sh\necho "Service restrictions: found"\n',
        'am': '#!/bin/sh\nprintf "am %s\\n" "$*" >> "$TRACE"\n',
        'prefs': '#!/bin/sh\nprintf "prefs %s\\n" "$*" >> "$TRACE"\nexit "$FAIL_CODE"\n',
        'content': '#!/bin/sh\necho "Error while accessing provider: unavailable" >&2\n',
        'getprop': '#!/bin/sh\nexit 0\n',
    }.items():
        executable = tools / name
        executable.write_text(content)
        executable.chmod(0o755)
    script = tmp_path / 'start.sh'
    script.write_text((ROOT / 'assets/frame-before-start.sh').read_text()
        .replace('/data/local/chrome-command-line', str(tmp_path / 'command-line'))
        .replace('/data/local/tmp/frame-webxr.json', str(tmp_path / 'frame-webxr.json'))
        .replace('/system/bin/app_process', str(tools / 'prefs')))
    env = {**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH'],
           'TRACE': str(trace), 'FAIL_CODE': '1' if failed else '0'}
    result = subprocess.run(['sh', str(script), 'org.chromium.chrome/com.google.android.apps.chrome.Main', 'allow'],
                            env=env, text=True, capture_output=True)
    assert (result.returncode != 0) == failed
    actions = trace.read_text().splitlines()
    assert actions[:2] == ['am force-stop org.chromium.chrome',
        'prefs /system/bin FrameBrowserPrefs org.chromium.chrome allow']
    assert actions[2:] == ([] if failed else ['am start -S org.chromium.chrome/com.google.android.apps.chrome.Main'])
    if not failed:
        assert 'Browser-Verknüpfung konnte nicht ergänzt werden' in result.stderr


@pytest.mark.parametrize('failure', ['exited', 'not_ready'])
def test_automatic_preloader_start_failure_is_bounded_and_browser_still_starts(tmp_path, failure):
    tools = tmp_path / 'bin'
    tools.mkdir()
    trace = tmp_path / 'trace'
    for name, content in {
        'service': '#!/bin/sh\necho "Service restrictions: found"\n',
        'am': '#!/bin/sh\nprintf "am %s\\n" "$*" >> "$TRACE"\n',
        'getprop': '#!/bin/sh\nexit 0\n',
        'content': '#!/bin/sh\nexit 1\n',
        'process': '#!/bin/sh\nprintf "process %s\\n" "$*" >> "$TRACE"\n'
            'case "$*" in *FrameBrowserXR*)\n'
            + ('sleep 4\n' if failure == 'not_ready' else '') + 'exit 1 ;; esac\n',
    }.items():
        executable = tools / name
        executable.write_text(content)
        executable.chmod(0o755)
    script = tmp_path / 'start.sh'
    script.write_text((ROOT / 'assets/frame-before-start.sh').read_text()
        .replace('/data/local/chrome-command-line', str(tmp_path / 'command-line'))
        .replace('/data/local/tmp/frame-webxr', str(tmp_path / 'frame-webxr'))
        .replace('/system/bin/app_process', str(tools / 'process')))
    result = subprocess.run(['sh', str(script), 'com.android.chrome/com.google.android.apps.chrome.Main', 'allow', 'auto'],
        env={**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH'], 'TRACE': str(trace)},
        text=True, capture_output=True, timeout=6)
    assert result.returncode == 0, result.stderr
    actions = trace.read_text().splitlines()
    assert 'FrameBrowserPrefs' in actions[1]
    assert 'FrameBrowserXR com.android.chrome' in actions[2]
    assert actions[-1] == 'am start -S com.android.chrome/com.google.android.apps.chrome.Main'
    assert 'Browser startet ohne diesen Helfer' in result.stderr


@pytest.mark.parametrize('mode', ['absent', 'existing', 'full', 'query_error', 'insert_error'])
@pytest.mark.parametrize('package', ['com.android.chrome', 'org.chromium.chrome'])
def test_home_shortcut_is_idempotent_and_preserves_occupied_slots(tmp_path, mode, package):
    content = tmp_path / 'content'
    content.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
assert os.environ['PARENT_UID'] == os.environ['PARENT_GID'] == '0'
mode = os.environ['MODE']
state = Path(os.environ['STATE'])
args = sys.argv[1:]
if args[0] == 'query':
    where = args[args.index('--where') + 1]
    if mode == 'query_error':
        print('Error while accessing provider: unavailable', file=sys.stderr)
    elif 'component=' in where:
        print('Row: 0 _id=3' if mode == 'existing' or state.exists() else 'No result found.')
    else:
        # Two occupied positions; a full hotseat occupies every position.
        occupied = mode == 'full' or 'screen=0 ' in where or 'screen=1 ' in where
        print('Row: 0 _id=2' if occupied else 'No result found.')
elif args[0] == 'insert':
    assert not state.exists(), 'duplicate shortcut inserted'
    assert 'screen:i:2' in args and 'rank:i:2' in args
    if mode == 'insert_error':
        print('Error while accessing provider: insert failed', file=sys.stderr)
    else:
        state.write_text(json.dumps(args))
''')
    content.chmod(0o755)
    script = tmp_path / 'shortcut.sh'
    # Exercise the actual provider helper without stopping a browser.
    source = (ROOT / 'assets/frame-before-start.sh').read_text().split('if ! service check')[0]
    script.write_text(source + '\nframe_home_shortcut "$1"\n')
    state = tmp_path / 'shortcut.json'
    env = {**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH'],
           'MODE': mode, 'STATE': str(state)}
    component = package + '/com.google.android.apps.chrome.Main'
    for _ in range(2):
        result = subprocess.run(['sh', str(script), component], env=env, text=True, capture_output=True)
        assert (result.returncode == 0) == (mode in ('absent', 'existing')), result.stderr
    assert state.exists() == (mode == 'absent')
    if state.exists():
        import json
        inserted = json.loads(state.read_text())
        assert f'title:s:{"Chrome" if package == "com.android.chrome" else "Chromium"}' in inserted
        assert any('component=' + component + ';end' in value for value in inserted)
