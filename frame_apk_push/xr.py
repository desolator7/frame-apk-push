"""Targeted ADB/CDP diagnostics. Never picks a device or browser implicitly."""
from __future__ import annotations
import json
import logging
import shutil
import subprocess
import time
import urllib.request
from contextlib import contextmanager, suppress
from urllib.parse import urlsplit, urlunsplit
from .core import ROOT, adb_path, validate_host, webxr_url, SAMPLES, CONTROLLER_SAMPLE
from . import network


class ManualTestRequired(RuntimeError):
    def __init__(self, message, browser_running=False):
        super().__init__(message)
        self.browser_running = browser_running


def run_adb(adb, serial, *args, timeout=20):
    result = subprocess.run([adb, '-s', serial, *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('ADB: ' + (result.stderr or result.stdout).strip())
    return result.stdout.strip()


def open_adb(host, timeout=20, port=5555):
    host = validate_host(host)
    adb = str(adb_path()) if adb_path().is_file() else shutil.which('adb')
    if not adb:
        raise RuntimeError('ADB fehlt. Bitte zuerst die Plattformwerkzeuge herunterladen.')
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Ungültiger ADB-Port.')
    serial = host + ':' + str(port)
    p = subprocess.run([adb, 'connect', serial], capture_output=True, text=True, timeout=timeout)
    if p.returncode or 'connected to' not in p.stdout.lower():
        raise RuntimeError('Lepton-ADB ist nicht erreichbar. Zuerst „Chromium am Frame starten“ ausführen. Falls der Browser sofort schließt, liegt ein Startfehler vor. Details: ' + (p.stdout + p.stderr).strip())
    # Verify Android, rather than the native Linux ADB endpoint.
    sdk = run_adb(adb, serial, 'shell', 'getprop', 'ro.build.version.sdk', timeout=timeout)
    if not sdk.isdigit():
        raise RuntimeError('Am gewählten ADB-Endpunkt läuft kein Android-Container.')
    return adb, serial


@contextmanager
def adb_connection(host, timeout=None):
    host = validate_host(host)
    interface = network.local_interface(host)
    options = {} if timeout is None else {'timeout': timeout}
    if not interface:
        yield open_adb(host, **options)
        return
    logging.info('Lepton-ADB direkt über %s (überlappende VPN-Route umgangen)', interface)
    with network.lan_tcp_forward(host, 5555, interface,
                                 timeout=min(5, timeout or 20)) as port:
        try:
            yield open_adb('127.0.0.1', port=port, **options)
        finally:
            # Remove only our temporary endpoint, including after a successful
            # connect followed by a failed Android check. Other ADB devices stay.
            adb = str(adb_path()) if adb_path().is_file() else shutil.which('adb')
            if adb:
                with suppress(OSError, subprocess.TimeoutExpired):
                    subprocess.run([adb, 'disconnect', f'127.0.0.1:{port}'],
                                   capture_output=True, timeout=3)


def wait_for_browser(host, package, timeout=30):
    validate_package(package)
    deadline = time.monotonic() + timeout
    detail = ''
    while time.monotonic() < deadline:
        try:
            with adb_connection(host, timeout=min(3, max(0.1, deadline - time.monotonic()))) as (adb, serial):
                pid = run_adb(adb, serial, 'shell', 'pidof', package, timeout=3)
                if pid:
                    return {'browser_running': True, 'pid': pid}
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            detail = str(error)
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    return {'browser_running': False, 'startup_warning':
            'Start angefordert, aber Chromium wurde über ADB nicht als laufend bestätigt. '
            'Browserbild am Headset prüfen; gegebenenfalls erneut starten. ' + detail}


def validate_test_page(url):
    return webxr_url(url)


def open_samples(host, package, url=SAMPLES):
    url = validate_test_page(url)
    # Lepton forwards ACTION_VIEW intents to Steam's overlay. CDP opens the
    # requested page inside the checked Android browser instead.
    try:
        with browser_debug(host, package) as (base, version):
            ws = open_cdp(version['webSocketDebuggerUrl'], base)
            try:
                targets = cdp_call(ws, 'Target.getTargets').get('targetInfos', [])
                existing = next((t for t in targets if t.get('type') == 'page'
                                 and t.get('url') == url), None)
                target = existing or cdp_call(ws, 'Target.createTarget', {'url': url})
                if not target.get('targetId'):
                    raise RuntimeError('Chromium hat keinen Tab für die Testseite angelegt.')
                cdp_call(ws, 'Target.activateTarget', {'targetId': target['targetId']})
            finally:
                ws.close()
        return {'samples_opened': True, 'url': url, 'method': 'CDP'}
    except ManualTestRequired as error:
        raise ManualTestRequired(str(error) + '\nTestseite im Chromium am Headset öffnen: ' + url,
                                 browser_running=error.browser_running) from error


def open_prepared_page(host, package, url):
    """Install early WebGL preparation for a user-selected secure web page."""
    url = validate_test_page(url)
    source = (ROOT / 'assets/frame-webxr.js').read_text()
    with browser_debug(host, package) as (base, version):
        browser_ws = open_cdp(version['webSocketDebuggerUrl'], base)
        page_ws = None
        try:
            targets = cdp_call(browser_ws, 'Target.getTargets').get('targetInfos', [])
            for target in targets:
                if target.get('type') == 'page' and target.get('url') == url:
                    closed = cdp_call(browser_ws, 'Target.closeTarget', {'targetId': target['targetId']})
                    if not closed.get('success'):
                        raise RuntimeError('Der bisherige Tab dieser Zieladresse konnte nicht beendet werden. Bitte am Headset schließen und wiederholen.')
            # A fresh document is required: adding xrCompatible after the game
            # created its context can lose GL resources and races XRWebGLLayer.
            target_id = cdp_call(browser_ws, 'Target.createTarget',
                                 {'url': 'about:blank'}).get('targetId')
            if not target_id:
                raise RuntimeError('Chromium hat keinen Tab für die Zieladresse angelegt.')
            deadline = time.monotonic() + 5
            while True:
                with urllib.request.urlopen(base + '/json/list', timeout=5) as response:
                    pages = json.load(response)
                page = next((p for p in pages if p.get('id') == target_id
                             and p.get('type') == 'page'), None)
                if page:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Der neue Browser-Tab ist nicht erreichbar.')
                time.sleep(0.1)
            page_ws = open_cdp(page['webSocketDebuggerUrl'], base)
            cdp_call(page_ws, 'Page.enable')
            script = cdp_call(page_ws, 'Page.addScriptToEvaluateOnNewDocument', {'source': source})
            if not script.get('identifier'):
                raise RuntimeError('Die VR-Grafikvorbereitung konnte nicht eingerichtet werden.')
            navigation = cdp_call(page_ws, 'Page.navigate', {'url': url})
            if navigation.get('errorText'):
                raise RuntimeError('Die Zieladresse konnte nicht geladen werden: ' + navigation['errorText'])
            cdp_call(browser_ws, 'Target.activateTarget', {'targetId': target_id})
            deadline = time.monotonic() + 45
            while True:
                probe = cdp_call(page_ws, 'Runtime.evaluate', {
                    'expression': '''(() => ({url: location.href,
                        loaded: document.readyState === "complete",
                        preparation: window.__frameWebXR || null,
                        load_error: !!document.getElementById("main-frame-error")}))()''',
                    'returnByValue': True}).get('result', {}).get('value', {})
                preparation = probe.get('preparation') or {}
                if probe.get('load_error'):
                    raise RuntimeError('Die Zieladresse zeigt einen Ladefehler. Internetverbindung am Frame prüfen.')
                # The selected destination may redirect to another secure page.
                # This target was blank before our navigation; the hook only
                # runs on secure web documents, so its presence identifies the
                # loaded page even when its final address differs.
                if preparation and probe.get('url') not in (None, '', 'about:blank'):
                    if not all(ctx.get('xrCompatible') for ctx in preparation.get('contexts', [])):
                        raise RuntimeError('Die Grafik konnte nicht für VR vorbereitet werden. Bitte Browser neu starten und wiederholen.')
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Die Zieladresse wurde nicht rechtzeitig mit VR-Grafikvorbereitung geladen. Bitte am Headset prüfen und wiederholen.')
                time.sleep(0.25)
            return {'page_opened': True, 'preparation_installed': True,
                    'graphics_prepared': bool(preparation.get('contexts')),
                    'preparation': preparation, 'url': probe['url'], 'requested_url': url, 'target_id': target_id,
                    'method': 'CDP', 'browser': version.get('Browser', '?'),
                    'browser_running': True, 'vr_verified': False}
        finally:
            if page_ws:
                page_ws.close()
            browser_ws.close()


def validate_package(package):
    import re
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]+', package):
        raise ValueError('Ungültiger Android-Paketname.')


def renderer_failure(log):
    return any('setresgid(' in line and 'failed: Invalid argument' in line
               and 'chrom' in line for line in log.splitlines())


def network_diagnose(host, package):
    validate_package(package)
    with adb_connection(host) as (adb, serial):
        return _network_diagnose_connected(adb, serial, package)


def _network_diagnose_connected(adb, serial, package):
    results = {}
    # Probe from inside Android. A working Linux host says nothing about the guest.
    for key, command in (
        ('ip', 'ping -c 1 -W 2 1.1.1.1'),
        ('dns', 'ping -c 1 -W 2 immersive-web.github.io'),
        ('https', 'curl -sS -o /dev/null -w "%{http_code}" --max-time 10 https://immersive-web.github.io/webxr-samples/')):
        try:
            detail = run_adb(adb, serial, 'shell', command, timeout=15)
            results[key] = {'ok': detail == '200' if key == 'https' else True, 'detail': detail}
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            results[key] = {'ok': False, 'detail': str(error)}
    processes = run_adb(adb, serial, 'shell', 'ps', '-A')
    log = run_adb(adb, serial, 'shell', 'logcat', '-d', '-t', '2000')
    failed = renderer_failure(log) and not any(package + ':sandboxed_process' in line for line in processes.splitlines())
    message = ('Lepton verhindert den Start isolierter Chromium-Seitenprozesse (setresgid). '
               'Dadurch bleiben Webseiten leer, obwohl der Container Internet hat. '
               'Diese Chromium-/Lepton-Kombination ist nicht als funktionsfähig bestätigt.' if failed else
               'Kein bekannter Chromium-Seitenprozessfehler im aktuellen Protokoll gefunden.')
    return {'network': results, 'renderer_failed': failed, 'message': message,
            'browser_running': any(line.split() and line.split()[-1] == package for line in processes.splitlines())}


def cdp_call(ws, method, params=None, timeout=20):
    cdp_call.sequence += 1
    ident = cdp_call.sequence
    ws.send(json.dumps({'id': ident, 'method': method, 'params': params or {}}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ws.settimeout(max(0.1, deadline - time.monotonic()))
        message = json.loads(ws.recv())
        if message.get('id') == ident:
            if 'error' in message:
                raise RuntimeError(str(message['error']))
            return message.get('result', {})
    raise TimeoutError('Chromium-Diagnose antwortet nicht rechtzeitig.')
cdp_call.sequence = 0


@contextmanager
def browser_debug(host, package):
    validate_package(package)
    with adb_connection(host) as (adb, serial):
        with _browser_debug_connected(adb, serial, package) as result:
            yield result


@contextmanager
def _browser_debug_connected(adb, serial, package):
    pid = run_adb(adb, serial, 'shell', 'pidof', package)
    if not pid:
        raise RuntimeError('Der vorbereitete Browser läuft im Lepton-Container nicht. Bitte am Frame starten.')
    # Public Chromium exposes either a static socket or one qualified with its main PID.
    deadline = time.monotonic() + 5
    while True:
        sockets = run_adb(adb, serial, 'shell', 'cat', '/proc/net/unix')
        candidates = set()
        for line in sockets.splitlines():
            name = line.split()[-1] if line.split() else ''
            if name == '@chrome_devtools_remote' or name in {f'@chrome_devtools_remote_{p}' for p in pid.split()}:
                # Accepted native helper connections can repeat the socket's
                # name in /proc/net/unix. They still identify one endpoint.
                candidates.add(name[1:])
        if candidates or time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    if len(candidates) != 1:
        log = run_adb(adb, serial, 'shell', 'logcat', '-d', '-t', '2000')
        processes = run_adb(adb, serial, 'shell', 'ps', '-A')
        if renderer_failure(log) and not any(package + ':sandboxed_process' in line
                                            for line in processes.splitlines()):
            raise ManualTestRequired('Chromium läuft, aber Lepton verhindert den Start seiner isolierten Seitenprozesse (setresgid). Webseiten und WebXR sind damit nicht funktionsfähig. „Android-Netzwerk und Seitenprozesse prüfen“ liefert die getrennte Diagnose.', browser_running=True)
        raise ManualTestRequired('Chromium läuft, aber seine Debugschnittstelle ist nicht eindeutig verfügbar. Bitte den manuellen XR-Test verwenden.', browser_running=True)
    local_port = run_adb(adb, serial, 'forward', 'tcp:0', 'localabstract:' + next(iter(candidates)))
    if not local_port.isdigit():
        raise RuntimeError('ADB konnte keinen lokalen Diagnose-Port bereitstellen.')
    base = f'http://127.0.0.1:{local_port}'
    try:
        with urllib.request.urlopen(base + '/json/version', timeout=5) as response:
            version = json.load(response)
        if version.get('Android-Package') != package:
            raise RuntimeError('Die Debugschnittstelle gehört nicht zum vorbereiteten Android-Browser.')
        yield base, version
    finally:
        run_adb(adb, serial, 'forward', '--remove', 'tcp:' + local_port)


def open_cdp(url, base):
    import websocket
    parts = urlsplit(url)
    if parts.scheme != 'ws' or not parts.path.startswith('/devtools/'):
        raise RuntimeError('Ungültige Chromium-Debugadresse.')
    # Never use a host supplied by the remote target.
    url = urlunsplit(('ws', urlsplit(base).netloc, parts.path, parts.query, ''))
    return websocket.create_connection(url, timeout=20, suppress_origin=True, http_proxy_host=None)


def diagnose(host, package, url=SAMPLES):
    url = validate_test_page(url)
    with browser_debug(host, package) as (base, version):
        with urllib.request.urlopen(base + '/json/list', timeout=5) as response:
            pages = json.load(response)
        # Check exactly the page opened by our button. Other samples may be in
        # background tabs, paused by a VR session or waiting on different input.
        pages = [p for p in pages if p.get('type') == 'page' and p.get('url') == url]
        if not pages:
            raise ManualTestRequired('Bitte zuerst „WebXR-Testseite öffnen“ klicken und die Seite im Headset laden lassen.', browser_running=True)
        ws = open_cdp(pages[0]['webSocketDebuggerUrl'], base)
        try:
            expression = '''(async () => ({secure: isSecureContext, xr: !!navigator.xr,
              immersive_vr: navigator.xr ? await navigator.xr.isSessionSupported("immersive-vr") : false,
              graphics_preparation: window.__frameWebXR || null,
              user_agent: navigator.userAgent, url: location.href, title: document.title,
              page_loaded: document.readyState === "complete" && !!document.body &&
                !document.getElementById("main-frame-error")}))()'''
            deadline = time.monotonic() + 15
            while True:
                result = cdp_call(ws, 'Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
                if 'exceptionDetails' in result:
                    raise RuntimeError('WebXR-Prüfung meldet: ' + json.dumps(result['exceptionDetails']))
                value = result.get('result', {}).get('value')
                if not isinstance(value, dict) or 'immersive_vr' not in value:
                    raise RuntimeError('Chromium liefert kein verwertbares XR-Prüfergebnis.')
                # A new tab initially has a complete about:blank document even
                # though /json/list already advertises its pending sample URL.
                if value.get('page_loaded') and value.get('url') == url:
                    break
                if time.monotonic() >= deadline:
                    raise ManualTestRequired('Die WebXR-Testseite ist noch nicht vollständig geladen oder zeigt einen Ladefehler. Bitte am Headset prüfen und erneut testen.', browser_running=True)
                time.sleep(0.25)
            return {**value, 'browser': version.get('Browser', '?'), 'browser_running': True,
                    'vr_verified': False}
        finally:
            ws.close()
