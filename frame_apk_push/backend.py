"""Valve adapter; imported only in the isolated worker."""
import sys
import re
from types import SimpleNamespace
from pathlib import Path
from .core import ROOT, GAME_ID, validate_host, inspect_apk, DATA

sys.path.insert(0, str(ROOT / 'vendor/steamos-devkit/client'))
import devkit_client as valve
from signalslot import Signal


def arguments(host, port=32000, **extra):
    host = validate_host(host)
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError('Ungültiger Devkit-Port.')
    return SimpleNamespace(machine=host, machine_name_type=valve.MachineNameType.ADDRESS,
                           http_port=port, login=None, **extra)


def deployment_matches(host, port, metadata):
    """Confirm the managed APK and helpers before allowing a resumed GUI start."""
    if not isinstance(metadata, dict) or not isinstance(metadata.get('runtime_helpers'), dict):
        return False
    names = {'ChromePublic.apk', 'launch-chromium.sh', 'frame-lepton-activity.sh',
             'libframe-zygote.so', 'frame-services.jar', 'frame-before-start.sh', 'frame-webxr.js', 'launcher-activity.txt'}
    expected = {'ChromePublic.apk': metadata.get('sha256', ''), **metadata['runtime_helpers']}
    if set(expected) != names or not all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) for value in expected.values()):
        return False
    args = arguments(host, port)
    if not any(game.get('gameid') == GAME_ID for game in valve.list_games(args)):
        return False
    ssh, _, _ = valve._open_ssh_for_args_all(args)
    try:
        # Fixed managed filenames only; no device/user input becomes shell code.
        files = ' '.join('"$HOME/devkit-game/' + GAME_ID + '/' + name + '"' for name in sorted(names))
        _, output, _ = ssh.exec_command('sha256sum -- ' + files, timeout=30)
        checked = {}
        for line in output.read().decode().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                checked[Path(parts[1]).name] = parts[0]
        return output.channel.recv_exit_status() == 0 and checked == expected
    finally:
        ssh.close()


def connect(host, port=32000, sync=True, metadata=None):
    args = arguments(host, port)
    ssh, _, machine = valve._open_ssh_for_args_all(args)
    ssh.close()
    if sync:
        valve.sync_utils(args, machine)
        status = valve.steamos_get_status(args) or {}
        if not status.get('is_deckard'):
            raise RuntimeError('Das verbundene Gerät wurde nicht als Steam Frame erkannt. Bitte Firmware und Zieladresse prüfen.')
    else:
        status = {}
    current = deployment_matches(host, port, metadata) if metadata and sync else False
    return {'host': machine.address, 'port': port, 'login': machine.login,
            'status': status, 'connected': True, 'deployment_current': current}


def pair(host, port=32000):
    result = valve.register(arguments(host, port))
    # An HTTP response alone is not proof that the user accepted pairing.
    connected = connect(host, port)
    return {**connected, 'pair_response': result}


def upload(host, port=32000, metadata=None):
    if not metadata:
        raise ValueError('Zuerst eine Chromium-APK vorbereiten.')
    path = Path(metadata['apk'])
    if path.resolve() != (DATA / 'deploy/ChromePublic.apk').resolve():
        raise ValueError('Die APK liegt nicht im verwalteten Deployment-Verzeichnis.')
    checked = inspect_apk(path)
    if checked['sha256'] != metadata['sha256']:
        raise ValueError('Die APK wurde nach der Prüfung verändert; bitte erneut vorbereiten.')
    launcher = checked.get('launcher_activity')
    if not launcher:
        raise ValueError('Die APK enthält keine startbare Launcher-Aktivität. Bitte erneut vorbereiten.')
    args = arguments(host, port, name=GAME_ID, directory=str(path.parent),
                     restart_steam=False, use_mask_unmask=False, prevent_auto_repair=False,
                     argv=['launch-chromium.sh'], delete_extraneous=True, skip_newer_files=False,
                     verify_checksums=True,
                     filter_args=['--include=/ChromePublic.apk', '--include=/lepton-show-flatscreen', '--include=/frame-lepton-activity.sh', '--include=/launch-chromium.sh', '--include=/libframe-zygote.so', '--include=/frame-services.jar', '--include=/frame-before-start.sh', '--include=/frame-webxr.js', '--include=/launcher-activity.txt', '--exclude=*'],
                     steam_play_debug=valve.SteamPlayDebug.Disabled, deps=[], cancel_signal=Signal(),
                     force_appid=None, env_vars={}, lepton_args='' ,
                     set_keyval=['steam_play=0', 'compat_tool=SteamLinuxRuntime_4-arm64'])
    if not valve.new_or_ensure_game(args):
        raise RuntimeError('Valve meldet einen fehlgeschlagenen Upload.')
    games = valve.list_games(arguments(host, port))
    if not any(game.get('gameid') == GAME_ID for game in games):
        raise RuntimeError('Upload abgeschlossen, aber der Devkit-Titel ist auf dem Frame nicht auffindbar.')
    return {'uploaded': True, 'gameid': GAME_ID, 'host': host, 'sha256': checked['sha256'], 'metadata': metadata}


def start(host, port=32000):
    args = arguments(host, port)
    devkit = SimpleNamespace(machine_command_args=(args.machine, args.machine_name_type), http_port=port, is_deckard=True)
    valve.run_game(devkit, GAME_ID)
    return {'start_requested': True}
