from pathlib import Path
import socket
import io
import pytest
from frame_apk_push import backend


def test_pair_rejection_is_not_connected(monkeypatch):
    monkeypatch.setattr(backend.valve, 'register', lambda args: 'rejected')
    def denied(*args, **kwargs):
        raise backend.valve.paramiko.AuthenticationException('Kopplung abgelehnt')
    monkeypatch.setattr(backend.valve, '_open_ssh_for_args_all', denied)
    with pytest.raises(backend.valve.paramiko.AuthenticationException):
        backend.pair('frame')


def test_connection_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise socket.timeout('Zeitüberschreitung')
    monkeypatch.setattr(backend.valve, '_open_ssh_for_args_all', timeout)
    with pytest.raises(socket.timeout):
        backend.connect('frame')


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    apk = tmp_path / 'deploy/ChromePublic.apk'
    apk.parent.mkdir()
    apk.write_bytes(b'test')
    monkeypatch.setattr(backend, 'inspect_apk', lambda p: {'sha256': 'correct', 'launcher_activity': 'com.google.android.apps.chrome.Main'})
    from types import SimpleNamespace
    monkeypatch.setattr(backend.valve, 'resolve_machine', lambda *a, **k: SimpleNamespace(login='steamos'))
    return {'apk': str(apk), 'sha256': 'correct'}


def test_upload_failed_is_not_success(tmp_path, monkeypatch):
    record = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(backend.valve, 'new_or_ensure_game', lambda args: False)
    with pytest.raises(RuntimeError, match='fehlgeschlagenen Upload'):
        backend.upload('frame', metadata=record)


def test_upload_verifies_title_and_runtime(tmp_path, monkeypatch):
    record = prepare(tmp_path, monkeypatch)
    calls = []
    def upload(args):
        calls.append(args)
        return True
    monkeypatch.setattr(backend.valve, 'new_or_ensure_game', upload)
    monkeypatch.setattr(backend.valve, 'list_games', lambda args: [{'gameid': backend.GAME_ID}])
    assert backend.upload('frame', metadata=record)['uploaded']
    assert calls[0].set_keyval == ['steam_play=0', 'compat_tool=SteamLinuxRuntime_4-arm64']
    assert calls[0].argv == ['launch-chromium.sh']
    assert calls[0].env_vars == {}
    assert '--include=/frame-lepton-activity.sh' in calls[0].filter_args
    monkeypatch.setattr(backend.valve, 'list_games', lambda args: [])
    with pytest.raises(RuntimeError, match='nicht auffindbar'):
        backend.upload('frame', metadata=record)


def test_modified_apk_not_uploaded(tmp_path, monkeypatch):
    record = prepare(tmp_path, monkeypatch)
    record['sha256'] = 'different'
    with pytest.raises(ValueError, match='verändert'):
        backend.upload('frame', metadata=record)


def test_start_supplies_complete_valve_device_interface(monkeypatch):
    calls = []
    class SSH: pass
    def opened(args):
        assert args.is_deckard is True
        assert args.machine == 'frame'
        assert args.http_port == 32000
        return SSH()
    monkeypatch.setattr(backend.valve, '_open_ssh_for_args', opened)
    monkeypatch.setattr(backend.valve, '_simple_ssh', lambda ssh, command, **kw: calls.append(command))
    assert backend.start('frame')['start_requested']
    assert 'Chromium_XR_Android' in calls[0]


@pytest.mark.parametrize('changed', [False, True])
def test_existing_deployment_start_requires_matching_apk_and_helpers(monkeypatch, changed):
    names = ['launch-chromium.sh', 'frame-lepton-activity.sh', 'libframe-zygote.so',
             'frame-services.jar', 'frame-before-start.sh', 'frame-webxr.js', 'launcher-activity.txt']
    expected = {'ChromePublic.apk': 'a' * 64, **{name: 'b' * 64 for name in names}}
    remote = dict(expected)
    if changed: remote['frame-before-start.sh'] = 'c' * 64
    output = io.BytesIO('\n'.join(f'{value}  /home/steamos/devkit-game/{backend.GAME_ID}/{name}'
                                for name, value in remote.items()).encode())
    from types import SimpleNamespace
    output.channel = SimpleNamespace(recv_exit_status=lambda: 0)
    class SSH:
        closed = False
        def exec_command(self, command, **kwargs):
            assert command.startswith('sha256sum -- ')
            assert '"$HOME/devkit-game/Chromium_XR_Android/frame-before-start.sh"' in command
            return None, output, None
        def close(self): self.closed = True
    ssh = SSH()
    monkeypatch.setattr(backend.valve, 'list_games', lambda *a: [{'gameid': backend.GAME_ID}])
    monkeypatch.setattr(backend.valve, '_open_ssh_for_args_all', lambda *a: (ssh, None, None))
    metadata = {'sha256': expected['ChromePublic.apk'], 'runtime_helpers': {name: expected[name] for name in names}}
    assert backend.deployment_matches('frame', 32000, metadata) is (not changed)
    assert ssh.closed
