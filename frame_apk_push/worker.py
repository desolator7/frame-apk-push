"""One cancellable process per operation. stdout is JSONL; stderr is diagnostic text."""
import json
import logging
import os
import signal
import sys
from pathlib import Path
from . import core


def emit(kind, **data):
    print(json.dumps({'type': kind, **data}, ensure_ascii=False), flush=True)


def progress(done, total):
    emit('progress', done=done, total=total)


def execute(action, payload):
    if action == 'check':
        return core.prerequisites()
    if action == 'discover':
        return {'devices': core.discover()}
    if action == 'download':
        return core.chromium(payload.get('flatscreen', True), progress, payload.get('auto_allow_vr', True),
                             payload.get('auto_xr_prepare', True))
    if action == 'local_apk':
        return core.stage_apk(Path(payload['path']), payload.get('flatscreen', True),
                              {'source': 'local', 'original_path': payload['path']}, payload.get('auto_allow_vr', True),
                              payload.get('auto_xr_prepare', True))
    if action == 'adb':
        return {'adb': core.install_adb(progress)}
    if action in ('connect', 'pair', 'upload', 'start'):
        from . import backend
        from .network import configure_valve
        interface = configure_valve(payload['host'], backend.valve)
        if interface:
            logging.info('Frame-Verbindung direkt über %s (überlappende VPN-Route umgangen)', interface)
        if action == 'upload':
            metadata = payload.get('metadata')
            if not metadata:
                raise ValueError('Zuerst eine APK vorbereiten.')
            if core.sha256(Path(metadata['apk'])) != metadata['sha256']:
                raise ValueError('Die APK wurde nach der Prüfung verändert; bitte erneut vorbereiten.')
            metadata = core.stage_apk(Path(metadata['apk']), payload.get('flatscreen', True), metadata,
                                      payload.get('auto_allow_vr', metadata.get('auto_allow_vr', True)),
                                      payload.get('auto_xr_prepare', metadata.get('auto_xr_prepare', True)))
            return backend.upload(payload['host'], payload.get('port', 32000), metadata)
        if action == 'connect':
            result = backend.connect(payload['host'], payload.get('port', 32000), metadata=payload.get('metadata'))
        else:
            result = getattr(backend, action)(payload['host'], payload.get('port', 32000))
        if action == 'start':
            from .xr import wait_for_browser
            if core.adb_path().is_file() or core.shutil.which('adb'):
                result.update(wait_for_browser(payload['host'], payload.get('package', 'org.chromium.chrome')))
        return result
    if action in ('samples', 'controllers', 'prepare_page', 'diagnose', 'network'):
        from . import xr
        if action == 'prepare_page':
            return xr.open_prepared_page(payload['host'], payload['package'], payload['url'])
        if action in ('samples', 'controllers'):
            url = core.CONTROLLER_SAMPLE if action == 'controllers' else core.SAMPLES
            return xr.open_samples(payload['host'], payload['package'], url)
        if action == 'diagnose':
            return xr.diagnose(payload['host'], payload['package'], payload.get('test_page', core.SAMPLES))
        return xr.network_diagnose(payload['host'], payload['package'])
    raise ValueError('Unbekannte Aktion: ' + action)



def error_message(error):
    from urllib.error import HTTPError
    if isinstance(error, HTTPError) and error.code == 403:
        return 'Frame lehnt die Anfrage ab (HTTP 403). Am Headset Einstellungen → Entwickler → Neuen Host koppeln öffnen und erneut koppeln.'
    hints = {
        'AuthenticationException': 'SSH-Anmeldung abgelehnt. Bitte am Frame „Neuen Host koppeln“ öffnen und die Kopplungsanfrage bestätigen.',
        'SSHException': 'SSH-Sitzung konnte nicht aufgebaut werden. Entwicklermodus und Kopplung am Frame prüfen. Details: ' + str(error),
        'TimeoutError': 'Zeitüberschreitung. Netzwerk/IP prüfen und sicherstellen, dass der Devkit-Dienst bzw. Lepton am Frame läuft.',
        'gaierror': 'Hostname nicht auflösbar. Bitte die WLAN-IP des Frames eingeben.',
        'WebSocketTimeoutException': 'Chromiums Debugschnittstelle antwortet nicht rechtzeitig. Testseite am Headset vollständig laden lassen, eine offene Browser-Freigabe bestätigen und die Prüfung wiederholen.',
    }
    return hints.get(type(error).__name__, str(error) or type(error).__name__)


def main():
    # Put all spawned ssh/rsync commands into the same cancellable process group.
    try:
        os.setsid()
    except PermissionError:
        if os.getsid(0) != os.getpid():
            raise
    def cancel(*_):
        raise core.Cancelled('Aktion abgebrochen. Sie kann erneut gestartet werden.')
    signal.signal(signal.SIGTERM, cancel)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(message)s')
    try:
        action = sys.argv[1]
        payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        emit('result', action=action, data=execute(action, payload))
        return 0
    except core.Cancelled as e:
        emit('cancelled', message=str(e))
        return 2
    except Exception as e:
        from .xr import ManualTestRequired
        if isinstance(e, ManualTestRequired):
            emit('manual', message=str(e), browser_running=e.browser_running)
            return 0
        logging.exception('Aktion fehlgeschlagen')
        message = error_message(e)
        emit('error', message=message, error_class=type(e).__name__)
        return 1

if __name__ == '__main__':
    sys.exit(main())
