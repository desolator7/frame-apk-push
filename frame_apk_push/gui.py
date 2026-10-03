"""German Qt desktop assistant. Device operations run out of process."""
from __future__ import annotations
import json
import os
from pathlib import Path
import signal
import sys
from datetime import datetime
from PySide6.QtCore import QProcess, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QLineEdit, QComboBox, QCheckBox, QProgressBar,
    QPlainTextEdit, QFileDialog, QGroupBox, QScrollArea, QMessageBox)
from .core import ROOT, DATA, GAME_ID, SAMPLES, CONTROLLER_SAMPLE, validate_host, webxr_url, redact

STYLE = '''
QWidget { background: #111a24; color: #e6edf5; font-size: 14px; }
QMainWindow { background: #111a24; }
QLabel#headline { font-size: 28px; font-weight: 700; }
QLabel#subheading { color: #95acbf; }
QGroupBox { border: 1px solid #304353; border-radius: 10px; margin-top: 16px; padding: 18px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; color: #82cde8; }
QPushButton { background: #253b4d; padding: 10px 16px; border-radius: 6px; border: 1px solid #395369; }
QPushButton:hover { background: #345069; }
QPushButton:disabled { color: #6f7e8c; background: #1a2632; border-color: #263744; }
QPushButton#primary { background: #2283a4; color: white; font-weight: 600; }
QPushButton#primary:disabled { background: #1a2632; color: #6f7e8c; border-color: #263744; }
QLineEdit, QComboBox, QPlainTextEdit { background: #0b131c; border: 1px solid #344b60; border-radius: 5px; padding: 8px; }
QTabWidget::pane { border: 1px solid #304353; border-radius: 7px; }
QTabBar::tab { background: #1a2b3b; padding: 12px 15px; margin-right: 3px; }
QTabBar::tab:selected { background: #25485d; color: #8fe1f2; }
QProgressBar { border: 1px solid #344b60; border-radius: 4px; text-align: center; min-height: 22px; }
QProgressBar::chunk { background: #2386a5; }
QCheckBox { spacing: 8px; }
'''


def text_label(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Frame APK Push · Chromium XR')
        self.resize(980, 850)
        self.process = None
        self.action = None
        self.last_job = None
        self.output_buffer = b''
        self.job_finished = False
        self.cancel_requested = False
        self.connected_target = None
        self.uploaded_target = None
        self.metadata = None
        self.xr_result = None
        self.test_page = SAMPLES
        self.statuses = {'installation': 'Noch nicht übertragen', 'browser': 'Noch nicht geprüft',
                         'xr': 'Noch nicht geprüft', 'vr': 'Noch nicht getestet'}
        self.buttons = []
        self.records = []
        self.config = {}
        self.last_acceptance = None
        try:
            saved_acceptance = json.loads((DATA / 'acceptance.json').read_text())
            if isinstance(saved_acceptance, dict):
                self.last_acceptance = saved_acceptance
        except (OSError, ValueError):
            pass
        try:
            self.config = json.loads((DATA / 'settings.json').read_text())
        except (OSError, ValueError):
            pass
        try:
            saved = json.loads((DATA / 'browser.json').read_text())
            if Path(saved['apk']).is_file():
                self.metadata = saved
        except (OSError, ValueError, KeyError):
            pass
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel('Chromium auf deinem Frame')
        title.setObjectName('headline')
        layout.addWidget(title)
        sub = QLabel('Verbinden · installieren · WebXR am Headset testen')
        sub.setObjectName('subheading')
        layout.addWidget(sub)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.setup_tab()
        self.device_tab()
        self.browser_tab()
        self.xr_tab()
        self.message = text_label('Bereit. Die Voraussetzungen werden geprüft.')
        layout.addWidget(self.message)
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        row.addWidget(self.progress, 1)
        self.cancel_button = QPushButton('Abbrechen')
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        self.retry = QPushButton('Wiederholen')
        self.retry.clicked.connect(self.repeat)
        self.retry.setEnabled(False)
        row.addWidget(self.retry)
        layout.addLayout(row)
        log_row = QHBoxLayout()
        self.log_toggle = QCheckBox('Diagnoseprotokoll anzeigen')
        self.log_toggle.toggled.connect(lambda enabled: self.log.setVisible(enabled))
        log_row.addWidget(self.log_toggle)
        log_row.addStretch()
        export = QPushButton('Protokoll exportieren')
        export.clicked.connect(self.export)
        log_row.addWidget(export)
        layout.addLayout(log_row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(170)
        self.log.setMaximumBlockCount(4000)
        self.log.hide()
        layout.addWidget(self.log)
        self.setCentralWidget(central)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_installation)
        self.timer.start(5000)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timeout)
        self.refresh_browser()
        self.refresh_statuses()
        self.update_controls()
        QTimer.singleShot(0, lambda: self.run('check'))

    def tab(self, title):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, title)
        return layout

    def button(self, layout, text, fn, primary=False):
        button = QPushButton(text)
        if primary:
            button.setObjectName('primary')
        button.clicked.connect(fn)
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def group(self, layout, title):
        box = QGroupBox(title)
        group_layout = QVBoxLayout(box)
        layout.addWidget(box)
        return group_layout

    def setup_tab(self):
        layout = self.tab('1  Vorbereitung')
        layout.addWidget(text_label('Diese App installiert einen offiziellen Chromium-ARM64-Snapshot oder eine vollständige lokale Chrome-/Chromium-APK auf deinem Steam Frame. WebXR über Lepton wird anschließend am Gerät geprüft.'))
        box = self.group(layout, 'Werkzeuge auf diesem PC')
        self.tools = text_label('Prüfung läuft …')
        box.addWidget(self.tools)
        self.button(box, 'Voraussetzungen erneut prüfen', lambda: self.run('check'))
        self.install_devkit = self.button(box, 'SteamOS Devkit Client installieren', self.steam_install, True)
        self.button(box, 'Google ADB-Plattformwerkzeuge herunterladen', lambda: self.run('adb'))
        box.addWidget(text_label('Steam zeigt seinen Installationsdialog. Danach erkennt die App den Devkit Client automatisch. SSH und rsync fehlen? Unter CachyOS: sudo pacman -S openssh rsync'))
        box = self.group(layout, 'Headset vorbereiten')
        box.addWidget(text_label('1. PC und Frame mit demselben Netzwerk verbinden.\n2. Am Frame: Einstellungen → System → Entwicklermodus aktivieren.\n3. Einstellungen → Entwickler → Neuen Host koppeln öffnen.\n4. Im nächsten Schritt das Frame auswählen und die Kopplung am Headset bestätigen.'))
        self.button(box, 'Weiter: Frame verbinden', lambda: self.tabs.setCurrentIndex(1))
        layout.addStretch()

    def device_tab(self):
        layout = self.tab('2  Frame verbinden')
        layout.addWidget(text_label('Die Suche findet Geräte mit Valves Devkit-Dienst. Falls das Frame fehlt, seine WLAN-IP oder seinen Hostnamen eingeben.'))
        box = self.group(layout, 'Steam Frame auswählen')
        self.devices = QComboBox()
        self.devices.addItem('Noch keine Geräte gesucht', None)
        self.devices.currentIndexChanged.connect(self.select_device)
        box.addWidget(self.devices)
        self.button(box, 'Im Netzwerk suchen', lambda: self.run('discover'))
        self.host = QLineEdit(self.config.get('host', 'frame'))
        self.host.setPlaceholderText('frame oder 203.0.113.50')
        self.host.textChanged.connect(self.target_changed)
        box.addWidget(self.host)
        self.port = QLineEdit(str(self.config.get('port', 32000)))
        self.port.setPlaceholderText('Devkit-Port, normalerweise 32000')
        self.port.textChanged.connect(self.target_changed)
        box.addWidget(self.port)
        self.connection = text_label('Noch keine Verbindung geprüft.')
        box.addWidget(self.connection)
        self.button(box, 'Koppeln – am Headset bestätigen', lambda: self.run_target('pair'), True)
        self.button(box, 'Bestehende Verbindung prüfen', lambda: self.run_target('connect'))
        box.addWidget(text_label('Koppeln nutzt Valves vorhandenen SSH-Schlüssel. Beim Prüfen werden wie im Valve Client die Devkit-Hilfsdateien aktualisiert.'))
        self.button(layout, 'Weiter: Chromium installieren', lambda: self.tabs.setCurrentIndex(2))
        layout.addStretch()

    def browser_tab(self):
        layout = self.tab('3  Chromium installieren')
        box = self.group(layout, 'Browser vorbereiten')
        box.addWidget(text_label('Download direkt aus Googles Chromium-Snapshot-Archiv: Android_Arm64 → ChromePublic.apk. Snapshots erhalten keine automatischen Updates; neue Revisionen werden nur auf deinen Klick geladen. Für H.264/AAC-Videos eine passende vollständige Chrome-/Chromium-APK lokal auswählen; der Standard-Snapshot unterstützt diese Codecs nicht. OpenXR und Videowiedergabe müssen am Frame geprüft werden.'))
        self.flatscreen = QCheckBox('Flatscreen-Marker für Browseroberfläche verwenden (experimentell)')
        self.flatscreen.setChecked(self.metadata.get('flatscreen', True) if self.metadata else True)
        self.flatscreen.toggled.connect(self.browser_mode_changed)
        box.addWidget(self.flatscreen)
        self.auto_allow_vr = QCheckBox('VR-Berechtigung automatisch erlauben (Abfrage umgehen)')
        self.auto_allow_vr.setChecked(self.metadata.get('auto_allow_vr', True) if self.metadata else True)
        self.auto_allow_vr.toggled.connect(self.browser_mode_changed)
        box.addWidget(self.auto_allow_vr)
        box.addWidget(text_label('Vermeidet den Absturz bei der ersten VR-Freigabe. Sichere Webseiten erhalten beim VR-Einstieg automatisch Zugriff auf Kopf- und Controllerbewegungen. Änderungen nach erneutem Übertragen und Browserstart aktiv; deaktiviert wird wieder gefragt.'))
        self.auto_xr_prepare = QCheckBox('VR-Grafikvorbereitung automatisch im Steam-Titel starten')
        self.auto_xr_prepare.setChecked(self.metadata.get('auto_xr_prepare', True) if self.metadata else True)
        self.auto_xr_prepare.toggled.connect(self.browser_mode_changed)
        box.addWidget(self.auto_xr_prepare)
        box.addWidget(text_label('Nach dem Übertragen und Neustart des Steam-Titels auch ohne PC aktiv: beliebige sichere WebXR-Seiten am Headset öffnen. Neue Tabs und Neuladen erhalten die Grafikvorbereitung automatisch.'))
        self.button(box, 'Offiziellen ARM64-Chromium herunterladen',
                    lambda: self.run('download', {'flatscreen': self.flatscreen.isChecked(),
                                                 'auto_allow_vr': self.auto_allow_vr.isChecked(),
                                                 'auto_xr_prepare': self.auto_xr_prepare.isChecked()}), True)
        self.button(box, 'Lokale ARM64-Browser-APK auswählen …', self.choose_apk)
        self.browser_details = text_label('Noch keine APK vorbereitet.')
        box.addWidget(self.browser_details)
        box = self.group(layout, 'Auf das gekoppelte Frame übertragen')
        box.addWidget(text_label(f'Devkit-Titel: {GAME_ID}\nStarthelfer: launch-chromium.sh → Lepton (Android)\nEin erneuter Upload aktualisiert denselben Titel.'))
        box.addWidget(text_label('Experimentelle Lepton-Anpassung für Chromium: behebt den Start der Seitenprozesse und ergänzt den benötigten Android-Dienst. Bitte vorerst nur vertrauenswürdige XR-Testseiten verwenden.'))
        self.upload_button = self.button(box, 'Chromium aufs Frame übertragen', lambda: self.run_target('upload'), True)
        self.start_button = self.button(box, 'Chromium am Frame starten', lambda: self.run_target('start'))
        self.button(layout, 'Weiter: XR testen', lambda: self.tabs.setCurrentIndex(3))
        layout.addStretch()

    def xr_tab(self):
        layout = self.tab('4  XR testen')
        box = self.group(layout, 'OpenXR im Browser aktivieren')
        box.addWidget(text_label('Im Chromium am Headset:\n\nchrome://flags/#enable-openxr-android → Enabled\nchrome://flags/#webxr-runtime → OpenXR\n\nMit „Relaunch“ übernehmen, anschließend Chromium bei Bedarf über diese App wieder starten. Bei „Google Play services / Device not compatible“ ist meist Cardboard aktiv: beide OpenXR-Einstellungen prüfen. Fehlen die Flags, ist dieser Build nicht als XR-fähig bestätigt.'))
        self.samples_button = self.button(box, 'WebXR-Testseite im Frame-Browser öffnen', lambda: self.run_target('samples'), True)
        self.controllers_button = self.button(box, 'Controller-Testseite im Frame-Browser öffnen', lambda: self.run_target('controllers'))
        box.addWidget(text_label('Beim Controller-Test „Enter VR“ wählen. Tasten ändern die Farbe der Kästchen; Sticks bewegen sie. Beide Controller prüfen.'))
        self.diagnose_button = self.button(box, 'Browser und WebXR automatisch prüfen', lambda: self.run_target('diagnose'))
        self.network_button = self.button(box, 'Android-Netzwerk und Seitenprozesse prüfen', lambda: self.run_target('network'))
        box = self.group(layout, 'WebXR-Seite mit vorbereiteter Grafik')
        box.addWidget(text_label('Bereitet die Grafik bereits beim Laden für den VR-Einstieg vor. Hilft bei Seiten, deren Grafik erst zu spät für VR eingerichtet wird.'))
        self.page_url = QLineEdit(self.config.get('webxr_url', SAMPLES))
        self.page_url.setPlaceholderText('https://… – beliebige WebXR-Zieladresse')
        box.addWidget(self.page_url)
        self.prepare_button = self.button(box, 'Mit VR-Grafikvorbereitung öffnen', lambda: self.run_target('prepare_page'))
        box.addWidget(text_label('Optionaler Start vom PC: öffnet deine Zieladresse in einem frischen Android-Browser-Tab und schließt ihre früheren Tabs. Am Headset „Enter VR“ wählen.\n\nMit aktivierter automatischer Vorbereitung im Steam-Titel kannst du die Adresse direkt am Headset öffnen; dieser Knopf ist dann nicht erforderlich. Nach einem Hänger den Steam-Titel vollständig beenden und neu starten.'))
        box = self.group(layout, 'Testergebnis')
        self.previous_acceptance = text_label('')
        box.addWidget(self.previous_acceptance)
        self.result_labels = {}
        for key, title in [('installation', 'Installation'), ('browser', 'Browser'), ('xr', 'WebXR-Unterstützung'), ('vr', 'Immersive VR')]:
            label = text_label(title + ': ' + self.statuses[key])
            self.result_labels[key] = (title, label)
            box.addWidget(label)
        self.manual = text_label(f'Falls die Debugschnittstelle fehlt: Testseite im Chromium am Headset öffnen und „Enter VR“ drücken.\nDarstellung: {SAMPLES}\nController-Eingabe: {CONTROLLER_SAMPLE}\n\nOptional über eine Browserkonsole: navigator.xr.isSessionSupported("immersive-vr"). Ein true bestätigt noch keine funktionierende VR-Sitzung.')
        box.addWidget(self.manual)
        self.render_ok = QCheckBox('Die immersive Sitzung zeigt die VR-Szene korrekt an')
        self.input_ok = QCheckBox('Controller-Eingabe funktioniert in der VR-Sitzung')
        for checkbox in (self.render_ok, self.input_ok):
            checkbox.toggled.connect(self.update_controls)
            box.addWidget(checkbox)
        self.verify_button = self.button(box, 'Erfolgreichen Gerätetest festhalten', self.verify_vr)
        self.failure = QLineEdit()
        self.failure.setPlaceholderText('Fehler beim VR-Versuch beschreiben …')
        box.addWidget(self.failure)
        self.button(box, 'Fehlgeschlagenen VR-Versuch festhalten', self.fail_vr)
        layout.addStretch()

    def target(self):
        host = validate_host(self.host.text())
        try:
            port = int(self.port.text())
        except ValueError:
            raise ValueError('Der Devkit-Port muss eine Zahl sein.')
        if not 1 <= port <= 65535:
            raise ValueError('Der Devkit-Port muss zwischen 1 und 65535 liegen.')
        return host, port

    def target_changed(self):
        if not hasattr(self, 'connection'):
            return
        self.connected_target = None
        self.uploaded_target = None
        self.connection.setText('Ziel geändert. Bitte Verbindung erneut prüfen.')
        self.reset_results()
        self.update_controls()

    def browser_mode_changed(self):
        self.uploaded_target = None
        self.reset_results()
        self.update_controls()

    def select_device(self):
        data = self.devices.currentData()
        if data:
            self.host.setText(data['host'])
            self.port.setText(str(data['port']))

    def reset_results(self):
        self.test_page = SAMPLES
        self.statuses.update(installation='Noch nicht übertragen', browser='Noch nicht geprüft',
                             xr='Noch nicht geprüft', vr='Noch nicht getestet')
        self.xr_result = None
        if hasattr(self, 'render_ok'):
            self.render_ok.setChecked(False)
            self.input_ok.setChecked(False)
        self.refresh_statuses()

    def refresh_statuses(self):
        for key, (title, label) in getattr(self, 'result_labels', {}).items():
            label.setText(title + ': ' + self.statuses[key])
        if hasattr(self, 'previous_acceptance'):
            accepted = self.last_acceptance
            matches = bool(accepted and self.metadata and
                accepted.get('host') == self.host.text() and
                accepted.get('sha256') == self.metadata.get('sha256') and
                accepted.get('runtime_helpers') == self.metadata.get('runtime_helpers') and
                accepted.get('flatscreen') == self.flatscreen.isChecked() and
                accepted.get('auto_allow_vr', False) == self.auto_allow_vr.isChecked() and
                accepted.get('auto_xr_prepare', False) == self.auto_xr_prepare.isChecked() and
                accepted.get('rendering') and accepted.get('controllers'))
            self.previous_acceptance.setVisible(matches)
            if matches:
                self.previous_acceptance.setText('Letzte bestätigte Geräteabnahme: ' + accepted.get('time', '?') +
                    '\nVR-Darstellung und beide Controller vom Nutzer bestätigt. Die aktuellen Laufzeitprüfungen stehen darunter.')

    def refresh_browser(self):
        if self.metadata:
            name = self.metadata.get('browser_name', 'Chromium')
            build = ('Release: ' + self.metadata['release'] if self.metadata.get('release') else
                     'Revision: ' + self.metadata.get('revision', 'lokale APK'))
            self.browser_details.setText(f"{name} {self.metadata['version']} · {self.metadata['architecture']}\n"
                f"Paket: {self.metadata['package']} · {build}\n"
                f"Startaktivität: {self.metadata.get('launcher_activity', 'bitte APK erneut vorbereiten')}\n"
                f"OpenXR-Hinweise in APK: {'gefunden; Gerätetest offen' if all(self.metadata.get('openxr_evidence', {'unknown': False}).values()) else 'nicht vollständig nachgewiesen'}\n"
                f"SHA-256: {self.metadata['sha256']}\nQuelle: {self.metadata['source']}")

    def log_line(self, text):
        clean = redact(text).strip()
        if clean:
            self.log.appendPlainText(clean)

    def update_controls(self):
        busy = self.process is not None
        for button in self.buttons:
            button.setEnabled(not busy)
        for widget in (self.host, self.port, self.devices, self.flatscreen, self.auto_allow_vr, self.auto_xr_prepare, self.page_url):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.retry.setEnabled(not busy and self.last_job is not None)
        connected = self.connected_target is not None
        self.upload_button.setEnabled(not busy and connected and self.metadata is not None)
        self.start_button.setEnabled(not busy and connected and self.uploaded_target == self.connected_target)
        self.samples_button.setEnabled(not busy and connected and self.metadata is not None)
        self.controllers_button.setEnabled(not busy and connected and self.metadata is not None)
        self.prepare_button.setEnabled(not busy and connected and self.metadata is not None)
        self.diagnose_button.setEnabled(not busy and connected and self.metadata is not None)
        self.network_button.setEnabled(not busy and connected and self.metadata is not None)
        self.verify_button.setEnabled(not busy and connected and self.metadata is not None and self.render_ok.isChecked() and self.input_ok.isChecked())

    def run_target(self, action):
        try:
            host, port = self.target()
        except ValueError as e:
            self.message.setText(str(e))
            return
        self.config.update(host=host, port=port)
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / 'settings.json').write_text(json.dumps(self.config))
        payload = {'host': host, 'port': port}
        if action == 'connect':
            payload['metadata'] = self.metadata
        if action == 'upload':
            payload['metadata'] = self.metadata
            payload['flatscreen'] = self.flatscreen.isChecked()
            payload['auto_allow_vr'] = self.auto_allow_vr.isChecked()
            payload['auto_xr_prepare'] = self.auto_xr_prepare.isChecked()
        if action in ('start', 'samples', 'controllers', 'prepare_page', 'diagnose', 'network'):
            if not self.metadata:
                self.message.setText('Zuerst eine APK vorbereiten.')
                return
            payload['package'] = self.metadata['package']
        if action in ('samples', 'controllers'):
            self.test_page = CONTROLLER_SAMPLE if action == 'controllers' else SAMPLES
        if action == 'prepare_page':
            try:
                payload['url'] = webxr_url(self.page_url.text())
            except ValueError as error:
                self.message.setText(str(error))
                return
            self.test_page = payload['url']
            self.config['webxr_url'] = self.test_page
            (DATA / 'settings.json').write_text(json.dumps(self.config))
        if action == 'diagnose':
            payload['test_page'] = self.test_page
        if action == 'pair':
            self.message.setText('Bitte die Kopplungsanfrage jetzt am Headset bestätigen.')
        self.run(action, payload)

    def run(self, action, payload=None):
        if self.process:
            return
        payload = payload or {}
        self.action = action
        self.active_payload = payload
        self.last_job = (action, payload)
        self.job_finished = False
        self.cancel_requested = False
        self.output_buffer = b''
        if action == 'upload':
            self.reset_results()
            self.uploaded_target = None
        if action in ('download', 'local_apk'):
            self.reset_results()
            self.uploaded_target = None
        if action in ('start', 'samples', 'controllers', 'prepare_page', 'diagnose'):
            self.statuses['vr'] = 'Noch nicht getestet'
            self.render_ok.setChecked(False)
            self.input_ok.setChecked(False)
            if action in ('start', 'samples', 'controllers', 'prepare_page'):
                self.statuses['xr'] = 'Noch nicht geprüft'
                self.xr_result = None
            self.refresh_statuses()
        self.log_line(f"{datetime.now().isoformat(timespec='seconds')} · {action}")
        labels = {'check': 'Voraussetzungen prüfen …', 'discover': 'Frame im Netzwerk suchen …',
                  'pair': 'Kopplungsanfrage läuft – bitte am Headset bestätigen.',
                  'connect': 'SSH-Verbindung und Frame prüfen …', 'download': 'Chromium herunterladen und prüfen …',
                  'local_apk': 'APK prüfen …', 'upload': 'Chromium übertragen …', 'start': 'Start am Frame anfordern …',
                  'adb': 'ADB-Plattformwerkzeuge herunterladen …', 'samples': 'WebXR-Testseite öffnen …',
                  'controllers': 'Controller-Testseite öffnen …',
                  'prepare_page': 'WebXR-Zieladresse laden und Grafik für VR vorbereiten …',
                  'diagnose': 'Browser und WebXR prüfen …', 'network': 'Android-Netzwerk und Seitenprozesse prüfen …'}
        self.message.setText(labels.get(action, action))
        self.progress.setRange(0, 0)
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(ROOT))
        process.readyReadStandardOutput.connect(self.read_output)
        process.readyReadStandardError.connect(lambda: self.log_line(bytes(process.readAllStandardError()).decode(errors='replace')))
        process.finished.connect(self.process_finished)
        process.errorOccurred.connect(self.process_error)
        process.start(sys.executable, ['-m', 'frame_apk_push.worker', action, json.dumps(payload)])
        self.deadline.start(1800000 if action in ('download', 'adb', 'upload') else 180000)
        self.update_controls()

    def read_output(self):
        self.output_buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.output_buffer:
            line, self.output_buffer = self.output_buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                self.log_line(line.decode(errors='replace'))
                continue
            self.handle_worker_event(event)

    def handle_worker_event(self, event):
        kind = event.get('type')
        if kind == 'progress':
            total = event['total']
            if total:
                self.progress.setRange(0, 100)
                self.progress.setValue(int(event['done'] / total * 100))
            self.progress.setFormat(f"{event['done'] / 1024**2:.1f} MiB" + (f" / {total / 1024**2:.1f} MiB" if total else ''))
            return
        self.records.append({'time': datetime.now().isoformat(), 'action': self.action, **event})
        self.log_line(json.dumps(event, ensure_ascii=False))
        self.job_finished = True
        if kind in ('error', 'cancelled', 'manual'):
            self.message.setText(event.get('message', 'Aktion fehlgeschlagen.'))
            if kind == 'manual':
                self.statuses['xr'] = 'Automatische Prüfung nicht verfügbar – manuellen Test durchführen'
                if event.get('browser_running'):
                    self.statuses['browser'] = 'Läuft – Android-Prozess über ADB bestätigt'
            if self.action in ('pair', 'connect'):
                self.connected_target = None
                self.connection.setText('Nicht verbunden: ' + event.get('message', ''))
            self.refresh_statuses()
            return
        if kind != 'result' or self.cancel_requested:
            return
        data = event['data']
        if self.action == 'check':
            programs = data['programs']
            self.tools.setText('\n'.join(f"{name}: {path or 'FEHLT'}" for name, path in programs.items()) +
                '\nDevkit Client: ' + (data['devkit_client'] or 'Noch nicht installiert') + '\nADB: ' + (data['adb'] or 'Noch nicht installiert'))
            missing = [name for name, path in programs.items() if not path]
            self.message.setText('Voraussetzungen geprüft.' +
                (' Fehlende Programme: ' + ', '.join(missing) if missing else ' Alle erforderlichen Programme gefunden.'))
            self.install_devkit.setText('SteamOS Devkit Client in Steam öffnen' if data['devkit_client'] else 'SteamOS Devkit Client installieren')
            if data['devkit_client']:
                self.waiting_install = False
        elif self.action == 'discover':
            self.devices.clear()
            self.devices.addItem('Gerät auswählen …', None)
            for device in data['devices']:
                self.devices.addItem(f"{device['name']} · {device['host']}:{device['port']}", device)
            self.message.setText(f"{len(data['devices'])} Devkit-Gerät(e) gefunden. Bei Bedarf Hostname/IP manuell eingeben.")
        elif self.action in ('pair', 'connect'):
            previously_uploaded = self.uploaded_target
            self.uploaded_target = None
            self.connected_target = (self.active_payload['host'], self.active_payload['port'])
            self.connection.setText(f"Verbunden mit Steam Frame: {data['host']} · SSH als {data['login']}")
            self.config.update(host=self.connected_target[0], port=self.connected_target[1])
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / 'settings.json').write_text(json.dumps(self.config))
            self.message.setText('Steam Frame verbunden. Chromium kann vorbereitet und übertragen werden.')
            if data.get('deployment_current'):
                self.uploaded_target = self.connected_target
                self.statuses['installation'] = 'Vorhandener Titel: APK und Starthelfer per SHA-256 bestätigt'
                self.message.setText('Steam Frame verbunden. Der vorhandene Chromium-Titel wurde geprüft und kann gestartet werden.')
            elif previously_uploaded:
                self.reset_results()
                self.message.setText('Steam Frame verbunden. Den Titel erneut übertragen; APK und Starthelfer wurden nicht als übereinstimmend bestätigt.')
        elif self.action in ('download', 'local_apk'):
            self.metadata = data
            self.refresh_browser()
            self.message.setText('ARM64-APK geprüft und für den Upload vorbereitet.')
        elif self.action == 'upload':
            prepared = data.get('metadata')
            if prepared and prepared.get('sha256') == self.metadata['sha256']:
                self.metadata = prepared
            self.metadata['flatscreen'] = self.active_payload['flatscreen']
            self.metadata['auto_allow_vr'] = self.active_payload.get('auto_allow_vr', True)
            self.metadata['auto_xr_prepare'] = self.active_payload.get('auto_xr_prepare', True)
            self.refresh_browser()
            self.uploaded_target = self.connected_target
            self.statuses['installation'] = 'Übertragen und Devkit-Titel auf dem Frame gefunden'
            self.message.setText('Upload abgeschlossen. Den Steam-Titel am Frame starten; läuft er bereits, vollständig beenden und neu starten.')
        elif self.action == 'start':
            if data.get('browser_running'):
                self.statuses['browser'] = 'Läuft – Android-Prozess über ADB bestätigt'
                self.message.setText('Chromium läuft. Browseroberfläche am Headset prüfen und XR-Flags einstellen.')
            else:
                self.statuses['browser'] = 'Start angefordert – Browserprozess nicht bestätigt'
                self.message.setText(data.get('startup_warning', 'Start angefordert. Browseroberfläche bitte am Headset prüfen.'))
        elif self.action == 'adb':
            self.message.setText('ADB-Plattformwerkzeuge bereit. Lepton muss für die Diagnose am Frame laufen.')
        elif self.action == 'samples':
            self.message.setText('WebXR-Testseite angefordert. Nach dem Laden automatisch prüfen oder „Enter VR“ am Headset wählen.')
        elif self.action == 'controllers':
            self.message.setText('Controller-Testseite angefordert. Am Headset „Enter VR“ wählen und Tasten sowie Sticks beider Controller prüfen.')
        elif self.action == 'prepare_page':
            self.test_page = data.get('url', self.test_page)
            self.statuses['browser'] = 'Läuft: ' + data['browser']
            if data.get('graphics_prepared'):
                self.message.setText('Die WebXR-Seite ist mit für VR vorbereiteter Grafik geladen. Am Headset „Enter VR“ wählen; anschließend Darstellung und Controller testen.')
            else:
                self.message.setText('Die VR-Grafikvorbereitung ist für diese Seite eingerichtet. Ihr Grafikkontext entsteht erst bei weiterer Bedienung. Am Headset „Enter VR“ wählen und testen.')
        elif self.action == 'network':
            checks = data['network']
            summary = ' · '.join(f"{name.upper()}: {'OK' if result['ok'] else 'fehlgeschlagen'}" for name, result in checks.items())
            self.message.setText(summary + '\n' + data['message'])
            if data['browser_running']:
                self.statuses['browser'] = ('Browser läuft, aber Seitenprozesse scheitern an Lepton' if data['renderer_failed'] else 'Läuft – Android-Prozess über ADB bestätigt')
            if data['renderer_failed']:
                self.statuses['xr'] = 'Nicht prüfbar – Chromium-Seitenprozesse starten nicht'
        elif self.action == 'diagnose':
            self.xr_result = data
            self.statuses['browser'] = f"Läuft: {data['browser']}"
            self.statuses['xr'] = ('immersive-vr wird unterstützt' if data['immersive_vr'] else 'immersive-vr wird nicht unterstützt')
            self.message.setText('WebXR geprüft. OpenXR-Flags am Headset prüfen; auch Cardboard kann immersive-vr melden. Die tatsächliche VR-Sitzung und Controller müssen am Headset getestet werden.')
        self.refresh_statuses()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.job_finished = True
            self.message.setText('Der Hintergrundprozess konnte nicht gestartet werden. Python-Umgebung prüfen.')
            self.process_finished(-1, QProcess.ExitStatus.CrashExit)

    def process_finished(self, code, status):
        if self.process is None:
            return
        self.read_output()
        self.deadline.stop()
        if self.cancel_requested:
            self.message.setText('Aktion abgebrochen. Bei einem Upload kann eine Teilübertragung vorliegen; erneut übertragen.')
        elif not self.job_finished:
            self.message.setText(f'Hintergrundprozess beendet ohne Ergebnis (Code {code}). Details im Protokoll.')
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if code == 0 and not self.cancel_requested else 0)
        self.progress.setFormat('%p%')
        self.process.deleteLater()
        self.process = None
        self.update_controls()

    def cancel(self):
        if not self.process:
            return
        self.cancel_requested = True
        self.cancel_button.setEnabled(False)
        self.message.setText('Abbruch läuft …')
        pid = self.process.processId()
        self.terminate_group(pid, signal.SIGTERM)
        QTimer.singleShot(2000, lambda: self.force_stop(pid))

    def terminate_group(self, pid, sig):
        if pid <= 0:
            return
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)
        except ProcessLookupError:
            pass

    def force_stop(self, pid):
        if self.process and self.process.processId() == pid:
            self.terminate_group(pid, signal.SIGKILL)

    def timeout(self):
        self.log_line('Zeitlimit überschritten. Prozess wird abgebrochen.')
        self.cancel()

    def repeat(self):
        if self.last_job:
            action, payload = self.last_job
            if action in ('pair', 'connect', 'upload', 'start', 'samples', 'controllers', 'prepare_page', 'diagnose', 'network'):
                self.run_target(action)
            else:
                self.run(action, payload)

    def steam_install(self):
        from .core import find_devkit_client
        if find_devkit_client():
            if QDesktopServices.openUrl(QUrl('steam://rungameid/943760')):
                self.message.setText('Installierten SteamOS Devkit Client in Steam geöffnet.')
            else:
                self.message.setText('Steam konnte nicht geöffnet werden. Devkit Client in Steam → Werkzeuge starten.')
            return
        if QDesktopServices.openUrl(QUrl('steam://install/943760')):
            self.waiting_install = True
            self.message.setText('Installation in Steam abschließen. Die App erkennt den Client anschließend automatisch.')
        else:
            self.message.setText('Steam konnte nicht geöffnet werden. SteamOS Devkit Client in Steam → Werkzeuge installieren.')

    def poll_installation(self):
        if getattr(self, 'waiting_install', False) and self.process is None:
            from .core import prerequisites
            if prerequisites()['devkit_client']:
                self.run('check')

    def choose_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Vollständige ARM64-Browser-APK auswählen', '', 'Android APK (*.apk)')
        if path:
            self.run('local_apk', {'path': path, 'flatscreen': self.flatscreen.isChecked(),
                                   'auto_allow_vr': self.auto_allow_vr.isChecked(),
                                   'auto_xr_prepare': self.auto_xr_prepare.isChecked()})

    def verify_vr(self):
        if not (self.render_ok.isChecked() and self.input_ok.isChecked()):
            return
        self.statuses['vr'] = 'Am Headset vom Nutzer bestätigt: Darstellung und Controller funktionieren'
        accepted = {'time': datetime.now().astimezone().isoformat(timespec='seconds'), 'type': 'hardware_acceptance',
                    'host': self.host.text(), 'sha256': self.metadata['sha256'],
                    'runtime_helpers': self.metadata.get('runtime_helpers'), 'flatscreen': self.flatscreen.isChecked(),
                    'auto_allow_vr': self.auto_allow_vr.isChecked(),
                    'auto_xr_prepare': self.auto_xr_prepare.isChecked(),
                    'rendering': True, 'controllers': True, 'source': 'user'}
        self.records.append(accepted)
        self.last_acceptance = accepted
        try:
            (DATA / 'acceptance.json').write_text(json.dumps(accepted, indent=2, ensure_ascii=False))
        except OSError as error:
            self.log_line('Geräteabnahme konnte nicht gespeichert werden: ' + str(error))
        self.message.setText('Erfolgreicher VR-Gerätetest festgehalten.')
        self.refresh_statuses()

    def fail_vr(self):
        reason = self.failure.text().strip()
        if not reason:
            self.message.setText('Bitte den beobachteten VR-Fehler beschreiben.')
            return
        self.statuses['vr'] = 'Fehlgeschlagen: ' + reason
        self.records.append({'time': datetime.now().isoformat(), 'type': 'hardware_failure',
                             'host': self.host.text(), 'message': reason})
        self.render_ok.setChecked(False)
        self.input_ok.setChecked(False)
        self.refresh_statuses()
        self.message.setText('Fehlgeschlagenen VR-Versuch festgehalten.')

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Diagnoseprotokoll speichern', 'frame-xr-diagnose.json', 'JSON (*.json)')
        if path:
            report = {'statuses': self.statuses, 'browser': self.metadata, 'xr': self.xr_result,
                      'last_hardware_test': self.last_acceptance,
                      'events': self.records, 'log': self.log.toPlainText()}
            try:
                Path(path).write_text(redact(json.dumps(report, indent=2, ensure_ascii=False)))
                self.message.setText('Diagnoseprotokoll gespeichert: ' + path)
            except OSError as e:
                self.message.setText('Protokoll konnte nicht gespeichert werden: ' + str(e))

    def closeEvent(self, event):
        if self.process:
            self.cancel()
            self.process.waitForFinished(2500)
            if self.process:
                self.force_stop(self.process.processId())
                self.process.waitForFinished(1000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setFont(QFont('Sans Serif', 10))
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
