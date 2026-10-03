"""Downloads, APK validation and local setup. No GUI imports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import time
import urllib.request
import zipfile
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'frame-apk-push'
CACHE = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'frame-apk-push'
SNAPSHOTS = 'https://storage.googleapis.com/chromium-browser-snapshots'
ADB_URL = 'https://dl.google.com/android/repository/platform-tools-latest-linux.zip'
SAMPLES = 'https://immersive-web.github.io/webxr-samples/immersive-vr-session.html'
CONTROLLER_SAMPLE = 'https://immersive-web.github.io/webxr-samples/controller-state.html'
GAME_ID = 'Chromium_XR_Android'  # Valve's IDs permit letters, digits, underscores and dots only.


class Cancelled(Exception):
    pass


def webxr_url(value: str) -> str:
    value = value.strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError('Bitte eine WebXR-Zieladresse ohne Leerzeichen eingeben.')
    if '://' not in value and not value.lower().startswith(('javascript:', 'data:', 'file:', 'chrome:')):
        value = 'https://' + value
    try:
        parts = urlsplit(value)
        hostname, port = parts.hostname, parts.port
    except ValueError as error:
        raise ValueError('Ungültige WebXR-Zieladresse.') from error
    if not hostname or parts.username is not None or parts.password is not None:
        raise ValueError('Bitte eine WebXR-Zieladresse ohne Zugangsdaten eingeben.')
    if parts.scheme not in ('http', 'https') or (parts.scheme == 'http' and
            hostname not in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('WebXR benötigt eine HTTPS-Zieladresse; HTTP ist nur für localhost möglich.')
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, parts.fragment))


def validate_host(host: str) -> str:
    host = host.strip()
    if not host or len(host) > 253 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.\-]*', host):
        raise ValueError('Bitte einen IPv4-Hostnamen oder eine IPv4-Adresse ohne Port eingeben.')
    return host


def steam_libraries(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    roots = [home / '.local/share/Steam', home / '.steam/steam', home / '.steam/root',
             home / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
    libraries = []
    for root in roots:
        if not root.exists():
            continue
        libraries.append(root.resolve())
        config = root / 'steamapps/libraryfolders.vdf'
        if config.exists():
            for path in re.findall(r'"path"\s+"([^"\n]+)"', config.read_text(errors='replace')):
                libraries.append(Path(path.replace('\\\\', '\\')))
    return list(dict.fromkeys(libraries))


def find_devkit_client(home: Path | None = None) -> str | None:
    for library in steam_libraries(home):
        folders = [library / 'steamapps/common/SteamOSDevkitClient']
        manifest = library / 'steamapps/appmanifest_943760.acf'
        if manifest.is_file():
            match = re.search(r'"installdir"\s+"([^"\n]+)"', manifest.read_text(errors='replace'))
            if match:
                relative = Path(match[1])
                if not relative.is_absolute() and '..' not in relative.parts:
                    folders.insert(0, library / 'steamapps/common' / relative)
        for folder in folders:
            for launcher in ('devkit-gui.sh', 'linux-client/devkit-gui.sh'):
                path = folder / launcher
                if path.is_file():
                    return str(path)
    return None


def prerequisites() -> dict:
    return {'programs': {name: shutil.which(name) for name in ('steam', 'ssh', 'rsync')},
            'devkit_client': find_devkit_client(),
            'adb': str(adb_path()) if adb_path().exists() else shutil.which('adb')}


def adb_path() -> Path:
    return DATA / 'platform-tools/adb'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, progress: Callable = lambda *a: None,
             opener=urllib.request.urlopen) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + '.part')
    try:
        with opener(url, timeout=30) as response, partial.open('wb') as stream:
            total = int(response.headers.get('Content-Length', 0))
            if total > 1024 ** 3:
                raise ValueError('Download ist unerwartet groß (über 1 GiB).')
            received = 0
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                received += len(chunk)
                if received > 1024 ** 3:
                    raise ValueError('Download überschreitet 1 GiB.')
                progress(received, total)
            if total and received != total:
                raise OSError(f'Download unvollständig: {received} von {total} Bytes.')
        partial.replace(destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def inspect_apk(path: Path) -> dict:
    from androguard.core.axml import AXMLPrinter
    from loguru import logger
    logger.disable('androguard')
    try:
        with zipfile.ZipFile(path) as apk:
            entries = apk.namelist()
            if not any(n.startswith('lib/arm64-v8a/') and n.endswith('.so') for n in entries):
                raise ValueError('Die APK enthält keine nativen ARM64-Bibliotheken.')
            markers = {b'enable-openxr-android': False, b'webxr-runtime': False, b'xrCreateInstance': False}
            for name in entries:
                if name.startswith('lib/arm64-v8a/') and name.endswith('.so'):
                    with apk.open(name) as native:
                        header = native.read(64)
                        if len(header) < 20 or header[:5] != b'\x7fELF\x02' or header[18:20] != b'\xb7\x00':
                            raise ValueError('Eine ARM64-Bibliothek enthält keinen gültigen AArch64-ELF-Header.')
                        tail = header
                        while chunk := native.read(1024 * 1024):
                            block = tail + chunk
                            for marker in markers:
                                markers[marker] |= marker in block
                            tail = block[-64:]
            manifest = AXMLPrinter(apk.read('AndroidManifest.xml')).get_xml_obj()
            if manifest is None:
                raise ValueError('Android-Manifest ist nicht lesbar.')
            android = '{http://schemas.android.com/apk/res/android}'
            if manifest.get('split'):
                raise ValueError('Split-APKs werden nicht unterstützt; eine vollständige Browser-APK auswählen.')
            package = manifest.get('package', '')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]+', package):
                raise ValueError('Ungültiger Paketname im Manifest.')
            launcher = launcher_activity(manifest, package)
            sdk = manifest.find('uses-sdk')
            return {'package': package, 'version': manifest.get(android + 'versionName', '?'),
                    'version_code': manifest.get(android + 'versionCode', '?'),
                    'min_sdk': sdk.get(android + 'minSdkVersion') if sdk is not None else None,
                    'launcher_activity': launcher,
                    'sha256': sha256(path), 'architecture': 'arm64-v8a',
                    'openxr_evidence': {key.decode(): value for key, value in markers.items()}}
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError('Keine gültige vollständige Android-APK mit Manifest.') from e



def launcher_activity(manifest, package):
    android = '{http://schemas.android.com/apk/res/android}'
    for node in manifest.findall('./application/*'):
        if node.tag not in ('activity', 'activity-alias') or node.get(android + 'enabled') == 'false':
            continue
        for intent in node.findall('intent-filter'):
            actions = {n.get(android + 'name') for n in intent.findall('action')}
            categories = {n.get(android + 'name') for n in intent.findall('category')}
            if 'android.intent.action.MAIN' in actions and 'android.intent.category.LAUNCHER' in categories:
                name = node.get(android + 'name', '')
                if not re.fullmatch(r'[A-Za-z_.][A-Za-z0-9_.$]*', name):
                    raise ValueError('Ungültiger Activity-Name im Android-Manifest.')
                if name.startswith('.'):
                    name = package + name
                elif '.' not in name:
                    name = package + '.' + name
                return name
    return None

def stage_apk(source: Path, flatscreen: bool, provenance: dict, auto_allow_vr: bool = True,
              auto_xr_prepare: bool = True) -> dict:
    metadata = inspect_apk(source)
    if not metadata.get('launcher_activity'):
        raise ValueError('Die Browser-APK enthält keine startbare MAIN/LAUNCHER-Aktivität.')
    stage = DATA / 'deploy'
    stage.mkdir(parents=True, exist_ok=True)
    # Keep the upload directory limited to precisely the files we own.
    target = stage / 'ChromePublic.apk'
    if source.resolve() != target.resolve():
        temporary = stage / 'ChromePublic.apk.part'
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    shutil.copyfile(ROOT / 'assets/lepton-activity.sh', stage / 'frame-lepton-activity.sh')
    shutil.copyfile(ROOT / 'assets/launch-chromium.sh', stage / 'launch-chromium.sh')
    shutil.copyfile(ROOT / 'assets/libframe-zygote.so', stage / 'libframe-zygote.so')
    shutil.copyfile(ROOT / 'assets/frame-services.jar', stage / 'frame-services.jar')
    shutil.copyfile(ROOT / 'assets/frame-before-start.sh', stage / 'frame-before-start.sh')
    shutil.copyfile(ROOT / 'assets/frame-webxr.js', stage / 'frame-webxr.js')
    (stage / 'launch-chromium.sh').chmod(0o755)
    (stage / 'launcher-activity.txt').write_text(metadata['launcher_activity'] + '\n' +
                                               ('allow' if auto_allow_vr else 'ask') + '\n' +
                                               ('auto' if auto_xr_prepare else 'off') + '\n')
    marker = stage / 'lepton-show-flatscreen'
    if flatscreen:
        marker.touch()
    else:
        marker.unlink(missing_ok=True)
    helpers = ('launch-chromium.sh', 'frame-lepton-activity.sh', 'libframe-zygote.so',
               'frame-services.jar', 'frame-before-start.sh', 'frame-webxr.js', 'launcher-activity.txt')
    record = {**provenance, **metadata, 'apk': str(target), 'directory': str(stage),
              'flatscreen': flatscreen, 'auto_allow_vr': auto_allow_vr, 'auto_xr_prepare': auto_xr_prepare, 'runtime_helpers':
              {name: sha256(stage / name) for name in helpers}}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'browser.json').write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return record


def chromium(flatscreen=True, progress=lambda *a: None, auto_allow_vr=True, auto_xr_prepare=True) -> dict:
    with urllib.request.urlopen(SNAPSHOTS + '/Android_Arm64/LAST_CHANGE', timeout=20) as response:
        revision = response.read(100).decode().strip()
    if not revision.isdigit():
        raise ValueError('Chromium liefert keine gültige Snapshot-Revision.')
    url = f'{SNAPSHOTS}/Android_Arm64/{revision}/chrome-android.zip'
    archive = download(url, CACHE / f'chromium-{revision}.zip', progress)
    apk_path = CACHE / f'ChromePublic-{revision}.apk'
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if n in ('chrome-android/apks/ChromePublic.apk',
                                                'chrome-android/ChromePublic.apk', 'apks/ChromePublic.apk')]
        if len(names) != 1:
            raise ValueError('Offizielles Archiv enthält keine eindeutige ChromePublic.apk.')
        if z.getinfo(names[0]).file_size > 1024 ** 3:
            raise ValueError('APK im Archiv ist unerwartet groß.')
        try:
            with z.open(names[0]) as source, apk_path.with_suffix('.part').open('wb') as dest:
                shutil.copyfileobj(source, dest)
            apk_path.with_suffix('.part').replace(apk_path)
        finally:
            apk_path.with_suffix('.part').unlink(missing_ok=True)
    return stage_apk(apk_path, flatscreen, {'source': url, 'revision': revision,
                      'archive_sha256': sha256(archive)}, auto_allow_vr, auto_xr_prepare)


def install_adb(progress=lambda *a: None) -> str:
    archive = download(ADB_URL, CACHE / 'platform-tools.zip', progress)
    temporary = DATA / 'platform-tools.new'
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                relative = Path(info.filename)
                if relative.parts[0] != 'platform-tools' or '..' in relative.parts or relative.is_absolute():
                    raise ValueError('Ungültiger Pfad im ADB-Archiv.')
                dest = temporary.joinpath(*relative.parts[1:])
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as source, dest.open('wb') as output:
                        shutil.copyfileobj(source, output)
                    dest.chmod(0o755 if dest.name == 'adb' else 0o644)
        if not (temporary / 'adb').is_file():
            raise ValueError('ADB fehlt im Google-Archiv.')
        destination = DATA / 'platform-tools'
        shutil.rmtree(destination, ignore_errors=True)
        temporary.replace(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return str(adb_path())


def discover(seconds=5) -> list[dict]:
    from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange
    devices = {}
    zc = Zeroconf()
    def changed(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Removed:
            devices.pop(name, None)
            return
        info = zeroconf.get_service_info(service_type, name, timeout=1500)
        if info:
            addresses = [a for a in info.parsed_addresses() if ':' not in a]
            if addresses:
                devices[name] = {'name': name.split('._steamos')[0], 'host': addresses[0],
                                 'port': info.port, 'server': info.server}
    browser = ServiceBrowser(zc, '_steamos-devkit._tcp.local.', handlers=[changed])
    try:
        time.sleep(seconds)
        return list(devices.values())
    finally:
        browser.cancel()
        zc.close()


def redact(text: str) -> str:
    text = re.sub(r'-----BEGIN [^\n]*PRIVATE KEY-----.*?-----END [^\n]*PRIVATE KEY-----',
                  '[privater Schlüssel entfernt]', text, flags=re.S)
    return re.sub(r'(?m)(ssh-rsa|ssh-ed25519)\s+[A-Za-z0-9+/=]+', '[SSH-Schlüssel entfernt]', text)
