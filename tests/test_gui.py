import json
import pytest
from PySide6.QtCore import QProcess
from frame_apk_push import gui


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(gui, 'DATA', tmp_path)
    # Suppress only startup probe; tests choose operations explicitly.
    original = gui.Window.run
    monkeypatch.setattr(gui.Window, 'run', lambda *a, **k: None)
    w = gui.Window()
    qtbot.addWidget(w)
    w.show()
    qtbot.wait(20)
    monkeypatch.setattr(gui.Window, 'run', original)
    return w


def test_real_worker_keeps_gui_responsive_and_cancels(window, qtbot):
    window.run('discover')
    qtbot.waitUntil(lambda: window.process.state() == QProcess.ProcessState.Running, timeout=5000)
    window.tabs.setCurrentIndex(3)
    assert window.tabs.currentIndex() == 3
    assert window.cancel_button.isEnabled()
    window.cancel()
    qtbot.waitUntil(lambda: window.process is None, timeout=6000)
    assert window.retry.isEnabled()
    assert 'abgebrochen' in window.message.text()
    assert window.statuses['vr'] == 'Noch nicht getestet'


def test_xr_true_does_not_mark_vr_success(window):
    window.action = 'diagnose'
    window.handle_worker_event({'type': 'result', 'data': {'immersive_vr': True, 'browser': 'Chromium 156'}})
    assert window.statuses['xr'] == 'immersive-vr wird unterstützt'
    assert window.statuses['vr'] == 'Noch nicht getestet'
    assert not window.verify_button.isEnabled()


def test_confirmed_browser_start_is_separate_from_xr_success(window):
    window.action = 'start'
    window.handle_worker_event({'type': 'result', 'data': {'start_requested': True, 'browser_running': True}})
    assert 'ADB bestätigt' in window.statuses['browser']
    assert window.statuses['xr'] == 'Noch nicht geprüft'
    assert window.statuses['vr'] == 'Noch nicht getestet'
    window.handle_worker_event({'type': 'result', 'data': {'start_requested': True, 'browser_running': False, 'startup_warning': 'Bitte erneut starten'}})
    assert 'nicht bestätigt' in window.statuses['browser']
    assert window.message.text() == 'Bitte erneut starten'


def test_manual_xr_diagnosis_preserves_confirmed_browser_status(window):
    window.action = 'diagnose'
    window.handle_worker_event({'type': 'manual', 'message': 'Debugschnittstelle fehlt', 'browser_running': True})
    assert 'ADB bestätigt' in window.statuses['browser']
    assert 'manuellen Test' in window.statuses['xr']
    assert window.statuses['vr'] == 'Noch nicht getestet'


def test_network_success_does_not_hide_renderer_failure(window):
    window.action = 'network'
    window.handle_worker_event({'type': 'result', 'data': {
        'network': {'ip': {'ok': True}, 'dns': {'ok': True}, 'https': {'ok': True}},
        'browser_running': True, 'renderer_failed': True, 'message': 'Seitenprozesse scheitern'}})
    assert 'HTTPS: OK' in window.message.text()
    assert 'Seitenprozesse scheitern' in window.statuses['browser']
    assert 'Nicht prüfbar' in window.statuses['xr']
    assert window.statuses['vr'] == 'Noch nicht getestet'


def test_installed_devkit_is_shown_and_button_opens_client(window):
    window.action = 'check'
    window.handle_worker_event({'type': 'result', 'data': {
        'programs': {'steam': '/usr/bin/steam', 'ssh': '/usr/bin/ssh', 'rsync': '/usr/bin/rsync'},
        'devkit_client': '/SteamOSDevkitClient/devkit-gui.sh', 'adb': '/adb'}})
    assert '/SteamOSDevkitClient/devkit-gui.sh' in window.tools.text()
    assert 'in Steam öffnen' in window.install_devkit.text()
    assert 'Alle erforderlichen Programme gefunden' in window.message.text()


def test_target_change_invalidates_results(window):
    window.connected_target = ('frame', 32000)
    window.uploaded_target = ('frame', 32000)
    window.statuses['vr'] = 'Erfolgreich'
    window.host.setText('203.0.113.9')
    assert window.connected_target is None
    assert window.uploaded_target is None
    assert window.statuses['vr'] == 'Noch nicht getestet'
    assert not window.upload_button.isEnabled()


def test_worker_error_is_retryable(window, qtbot):
    window.run('local_apk', {'path': '/does/not/exist.apk'})
    qtbot.waitUntil(lambda: window.process is None, timeout=6000)
    assert window.retry.isEnabled()
    assert window.statuses['installation'] == 'Noch nicht übertragen'
    assert 'exist.apk' in window.message.text()


def test_browser_restored_without_device_settings(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(gui, 'DATA', tmp_path)
    monkeypatch.setattr(gui.Window, 'run', lambda *a, **k: None)
    apk = tmp_path / 'ChromePublic.apk'
    apk.write_bytes(b'fixture')
    metadata = {'apk': str(apk), 'package': 'org.chromium.chrome', 'version': '157',
                'architecture': 'arm64-v8a', 'sha256': 'hash', 'source': 'local'}
    (tmp_path / 'browser.json').write_text(json.dumps(metadata))
    w = gui.Window()
    qtbot.addWidget(w)
    assert w.metadata == metadata
    assert '157' in w.browser_details.text()
    assert not w.upload_button.isEnabled()


def test_controller_test_selects_the_matching_diagnosis_page(window, monkeypatch):
    window.metadata = {'package': 'org.chromium.chrome'}
    calls = []
    monkeypatch.setattr(window, 'run', lambda action, payload: calls.append((action, payload)))
    window.run_target('controllers')
    window.run_target('diagnose')
    assert calls[-1][1]['test_page'] == gui.CONTROLLER_SAMPLE
    assert calls[0][1]['package'] == 'org.chromium.chrome'
    window.host.setText('another-frame')
    assert window.test_page == gui.SAMPLES


@pytest.mark.parametrize('prepared', [True, False])
def test_selected_url_opens_installed_browser_and_keeps_vr_test_pending(window, monkeypatch, prepared):
    window.metadata = {'package': 'com.android.chrome'}
    window.connected_target = (window.host.text(), 32000)
    window.update_controls()
    assert window.prepare_button.isEnabled()
    window.page_url.setText('example.org/vr?test=1')
    calls = []
    monkeypatch.setattr(window, 'run', lambda action, payload: calls.append((action, payload)))
    window.prepare_button.click()
    window.run_target('diagnose')
    assert calls[0][0] == 'prepare_page' and calls[0][1]['package'] == 'com.android.chrome'
    assert calls[0][1]['url'] == 'https://example.org/vr?test=1'
    assert calls[1][1]['test_page'] == calls[0][1]['url']
    window.action = 'prepare_page'
    window.handle_worker_event({'type': 'result', 'data': {
        'graphics_prepared': prepared, 'browser': 'Chrome/154', 'vr_verified': False}})
    assert ('vorbereiteter Grafik' if prepared else 'erst bei weiterer Bedienung') in window.message.text()
    assert window.statuses['vr'] == 'Noch nicht getestet'


def test_reconnect_can_resume_a_verified_existing_title(window):
    window.action = 'connect'
    window.active_payload = {'host': 'frame', 'port': 32000}
    window.metadata = {'package': 'org.chromium.chrome'}
    window.handle_worker_event({'type': 'result', 'data': {
        'host': 'frame', 'login': 'steamos', 'deployment_current': True}})
    window.update_controls()
    assert window.start_button.isEnabled()
    assert 'SHA-256 bestätigt' in window.statuses['installation']
    assert window.statuses['vr'] == 'Noch nicht getestet'


def test_failed_deployment_match_invalidates_previous_start_permission(window):
    window.action = 'connect'
    window.active_payload = {'host': 'frame', 'port': 32000}
    window.metadata = {'package': 'org.chromium.chrome'}
    window.uploaded_target = ('frame', 32000)
    window.statuses['vr'] = 'Zuvor bestätigt'
    window.handle_worker_event({'type': 'result', 'data': {
        'host': 'frame', 'login': 'steamos', 'deployment_current': False}})
    window.update_controls()
    assert not window.start_button.isEnabled()
    assert window.uploaded_target is None
    assert window.statuses['vr'] == 'Noch nicht getestet'


def test_previous_acceptance_is_historical_and_bound_to_the_target(window):
    window.metadata = {'sha256': 'apk-hash', 'runtime_helpers': {'helper': 'hash'}}
    window.last_acceptance = {'time': '2026-10-01', 'host': window.host.text(),
        'sha256': 'apk-hash', 'runtime_helpers': {'helper': 'hash'},
        'flatscreen': True, 'auto_allow_vr': True, 'auto_xr_prepare': True, 'rendering': True, 'controllers': True}
    window.refresh_statuses()
    assert not window.previous_acceptance.isHidden()
    assert 'Letzte bestätigte Geräteabnahme' in window.previous_acceptance.text()
    assert window.statuses['vr'] == 'Noch nicht getestet'
    window.host.setText('different-frame')
    assert window.previous_acceptance.isHidden()


@pytest.mark.parametrize('mode', ['auto_allow_vr', 'auto_xr_prepare'])
def test_browser_mode_invalidates_start_and_is_sent_on_upload(window, monkeypatch, mode):
    window.metadata = {'package': 'org.chromium.chrome'}
    window.connected_target = (window.host.text(), 32000)
    window.uploaded_target = window.connected_target
    window.statuses['vr'] = 'Erfolgreich'
    getattr(window, mode).setChecked(False)
    assert window.uploaded_target is None
    assert not window.start_button.isEnabled()
    assert window.statuses['vr'] == 'Noch nicht getestet'
    calls = []
    monkeypatch.setattr(window, 'run', lambda action, payload: calls.append((action, payload)))
    window.run_target('upload')
    assert calls[-1][1][mode] is False
