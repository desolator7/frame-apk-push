import io
from pathlib import Path
import zipfile
import pytest
from frame_apk_push import core


class Response(io.BytesIO):
    def __init__(self, data, total=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data) if total is None else total)}


def test_interrupted_download_preserves_existing_file(tmp_path):
    target = tmp_path / 'browser.zip'
    target.write_bytes(b'previous')
    with pytest.raises(OSError, match='unvollständig'):
        core.download('https://example.invalid/a', target, opener=lambda *a, **k: Response(b'abc', 20))
    assert target.read_bytes() == b'previous'
    assert not target.with_suffix('.zip.part').exists()


def test_download_cancellation_removes_partial(tmp_path):
    def cancel(*a):
        raise core.Cancelled()
    with pytest.raises(core.Cancelled):
        core.download('https://example.invalid/a', tmp_path / 'browser.zip', cancel,
                      opener=lambda *a, **k: Response(b'abc'))
    assert not list(tmp_path.iterdir())


def test_download_progress_and_atomic_success(tmp_path):
    updates = []
    target = core.download('https://example.invalid/a', tmp_path / 'file',
                           lambda *a: updates.append(a), opener=lambda *a, **k: Response(b'abc'))
    assert target.read_bytes() == b'abc'
    assert updates == [(3, 3)]


@pytest.mark.parametrize('value', ['-evil', 'user@frame', 'frame;id', 'frame:22', '', 'frame\nfoo'])
def test_invalid_hosts(value):
    with pytest.raises(ValueError):
        core.validate_host(value)


def test_steam_alternate_library(tmp_path):
    root = tmp_path / '.local/share/Steam'
    (root / 'steamapps').mkdir(parents=True)
    (root / 'steamapps/libraryfolders.vdf').write_text('"path" "/mnt/games"')
    assert core.steam_libraries(tmp_path) == [root, Path('/mnt/games')]


@pytest.mark.parametrize('launcher', ['devkit-gui.sh', 'linux-client/devkit-gui.sh'])
def test_devkit_launcher_layouts(tmp_path, launcher):
    path = tmp_path / '.local/share/Steam/steamapps/common/SteamOSDevkitClient' / launcher
    path.parent.mkdir(parents=True)
    path.touch()
    assert core.find_devkit_client(tmp_path) == str(path)


def test_devkit_manifest_in_alternate_library(tmp_path):
    root = tmp_path / '.local/share/Steam/steamapps'
    root.mkdir(parents=True)
    alternate = tmp_path / 'Other Steam Library'
    (root / 'libraryfolders.vdf').write_text(f'"path" "{alternate}"')
    apps = alternate / 'steamapps'
    apps.mkdir(parents=True)
    (apps / 'appmanifest_943760.acf').write_text('"installdir" "Devkit Client"')
    assert core.find_devkit_client(tmp_path) is None  # Manifest alone is insufficient.
    launcher = apps / 'common/Devkit Client/devkit-gui.sh'
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    assert core.find_devkit_client(tmp_path) == str(launcher)


def test_rejects_non_apk_and_wrong_architecture(tmp_path):
    path = tmp_path / 'app.apk'
    path.write_bytes(b'not zip')
    with pytest.raises(ValueError, match='gültige'):
        core.inspect_apk(path)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('lib/armeabi-v7a/libchrome.so', b'ELF')
        z.writestr('AndroidManifest.xml', b'invalid')
    with pytest.raises(ValueError, match='ARM64'):
        core.inspect_apk(path)


def test_stage_metadata_and_flatscreen_toggle(tmp_path, monkeypatch):
    from lxml import etree
    import androguard.core.axml
    manifest = etree.fromstring(b'<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.chromium.chrome" android:versionName="156" android:versionCode="123"><uses-sdk android:minSdkVersion="29"/><application><activity-alias android:name="com.google.android.apps.chrome.Main" android:targetActivity="org.chromium.chrome.browser.ChromeTabbedActivity"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity-alias></application></manifest>')
    class Parser:
        def __init__(self, data): pass
        def get_xml_obj(self): return manifest
    monkeypatch.setattr(androguard.core.axml, 'AXMLPrinter', Parser)
    monkeypatch.setattr(core, 'DATA', tmp_path / 'data')
    source = tmp_path / 'input.apk'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('AndroidManifest.xml', b'AXML')
        z.writestr('lib/arm64-v8a/libchrome.so', b'\x7fELF\x02' + b'\x00' * 13 + b'\xb7\x00' + b'\x00' * 44 + b'enable-openxr-android webxr-runtime xrCreateInstance')
    record = core.stage_apk(source, True, {'source': 'local'})
    assert record['package'] == 'org.chromium.chrome'
    assert record['min_sdk'] == '29'
    assert all(record['openxr_evidence'].values())
    assert (core.DATA / 'deploy/lepton-show-flatscreen').is_file()
    assert record['runtime_helpers']['libframe-zygote.so'] == core.sha256(core.DATA / 'deploy/libframe-zygote.so')
    assert (core.DATA / 'deploy/frame-services.jar').is_file()
    assert record['auto_allow_vr']
    assert record['auto_xr_prepare']
    assert record['runtime_helpers']['frame-webxr.js'] == core.sha256(core.DATA / 'deploy/frame-webxr.js')
    assert (core.DATA / 'deploy/launcher-activity.txt').read_text().splitlines()[1:] == ['allow', 'auto']
    second = core.stage_apk(Path(record['apk']), False, record, auto_allow_vr=False, auto_xr_prepare=False)
    assert second['sha256'] == record['sha256']
    assert not (core.DATA / 'deploy/lepton-show-flatscreen').exists()
    assert not second['auto_allow_vr']
    assert not second['auto_xr_prepare']
    assert (core.DATA / 'deploy/launcher-activity.txt').read_text().splitlines()[1:] == ['ask', 'off']
    assert second['runtime_helpers']['launcher-activity.txt'] != record['runtime_helpers']['launcher-activity.txt']
    manifest.set('split', 'config.arm64_v8a')
    with pytest.raises(ValueError, match='Split'):
        core.inspect_apk(source)


def test_discovery_handles_add_remove_and_ipv4(monkeypatch):
    import zeroconf
    class Info:
        port = 32000
        server = 'frame.local.'
        def parsed_addresses(self): return ['fe80::1', '203.0.113.8']
    class ZC:
        closed = False
        def get_service_info(self, *a, **k): return Info()
        def close(self): self.closed = True
    instances = []
    class Browser:
        def __init__(self, zc, service, handlers):
            instances.append(self)
            self.cancelled = False
            callback = handlers[0]
            callback(zc, service, 'gone.' + service, zeroconf.ServiceStateChange.Added)
            callback(zc, service, 'gone.' + service, zeroconf.ServiceStateChange.Removed)
            callback(zc, service, 'frame.' + service, zeroconf.ServiceStateChange.Added)
        def cancel(self): self.cancelled = True
    monkeypatch.setattr(zeroconf, 'Zeroconf', ZC)
    monkeypatch.setattr(zeroconf, 'ServiceBrowser', Browser)
    assert core.discover(0) == [{'name': 'frame', 'host': '203.0.113.8', 'port': 32000, 'server': 'frame.local.'}]
    assert instances[0].cancelled


def test_export_redacts_private_key():
    text = 'before\n-----BEGIN RSA PRIVATE KEY-----\nsecret\n-----END RSA PRIVATE KEY-----\nafter ssh-rsa AAAABBBB comment'
    cleaned = core.redact(text)
    assert 'secret' not in cleaned and 'AAAABBBB' not in cleaned
    assert 'before' in cleaned and 'after' in cleaned


@pytest.mark.parametrize('value, expected', [
    ('example.org/game?mode=vr#start', 'https://example.org/game?mode=vr#start'),
    (' https://example.org ', 'https://example.org/'),
    ('http://localhost:8000/game', 'http://localhost:8000/game'),
    ('https://[::1]:443/', 'https://[::1]:443/')])
def test_user_selected_webxr_url(value, expected):
    assert core.webxr_url(value) == expected


@pytest.mark.parametrize('value', ['', 'https://a b/', 'javascript:alert(1)',
    'file:///private', 'data:text/html,test', 'chrome://flags', 'https://user:pass@example.org/',
    'http://example.org/', 'https://example.org:99999/', 'https:///path'])
def test_invalid_or_insecure_webxr_url(value):
    with pytest.raises(ValueError):
        core.webxr_url(value)
