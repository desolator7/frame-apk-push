"""Small runtime translation catalog for the desktop interface."""
from __future__ import annotations

import json
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton


LANGUAGE = 'en'


def set_language(language: str) -> None:
    global LANGUAGE
    LANGUAGE = language if language in ('en', 'de') else 'en'

ENGLISH = {
    'Sprache': 'Language',
    'Frame APK Push · WebXR auf Steam Frame': 'Frame APK Push · WebXR for Steam Frame',
    'XR-Browser auf deinem Frame': 'XR browser on your Frame',
    'Verbinden · installieren · WebXR am Headset testen': 'Connect · install · use WebXR on your headset',
    '1  Vorbereitung': '1  Setup',
    '2  Frame verbinden': '2  Connect Frame',
    '3  Chromium installieren': '3  Install Chromium',
    '4  XR testen': '4  XR tools',
    'Bereit. Die Voraussetzungen werden geprüft.': 'Ready. Checking requirements.',
    'Abbrechen': 'Cancel',
    'Wiederholen': 'Retry',
    'Diagnoseprotokoll anzeigen': 'Show diagnostic log',
    'Protokoll exportieren': 'Export report',
    'Diese App installiert einen offiziellen Chromium-ARM64-Snapshot oder eine vollständige lokale Chrome-/Chromium-APK auf deinem Steam Frame. WebXR über Lepton wird anschließend am Gerät geprüft.': 'This app installs an official Chromium ARM64 snapshot or a complete local Chrome/Chromium APK on your Steam Frame. WebXR through Lepton can then be checked on the device.',
    'Werkzeuge auf diesem PC': 'Tools on this PC',
    'Prüfung läuft …': 'Checking …',
    'Voraussetzungen erneut prüfen': 'Check requirements again',
    'SteamOS Devkit Client installieren': 'Install SteamOS Devkit Client',
    'Google ADB-Plattformwerkzeuge herunterladen': 'Download Google ADB platform tools',
    'Headset vorbereiten': 'Prepare the headset',
    '1. PC und Frame mit demselben Netzwerk verbinden.\n2. Am Frame: Einstellungen → System → Entwicklermodus aktivieren.\n3. Einstellungen → Entwickler → Neuen Host koppeln öffnen.\n4. Im nächsten Schritt das Frame auswählen und die Kopplung am Headset bestätigen.': '1. Connect the PC and Frame to the same network.\n2. On Frame, enable Settings → System → Developer Mode.\n3. Open Settings → Developer → Pair New Host.\n4. Select Frame in the next step and confirm pairing on the headset.',
    'Weiter: Frame verbinden': 'Next: Connect Frame',
    'Die Suche findet Geräte mit Valves Devkit-Dienst. Falls das Frame fehlt, seine WLAN-IP oder seinen Hostnamen eingeben.': 'Discovery finds devices running Valve’s Devkit service. If Frame is not listed, enter its Wi-Fi IP address or hostname.',
    'Steam Frame auswählen': 'Select Steam Frame',
    'Noch keine Geräte gesucht': 'No devices found yet',
    'Im Netzwerk suchen': 'Search network',
    'frame oder 203.0.113.50': 'frame or 203.0.113.50',
    'Devkit-Port, normalerweise 32000': 'Devkit port, usually 32000',
    'Noch keine Verbindung geprüft.': 'Connection has not been checked yet.',
    'Koppeln – am Headset bestätigen': 'Pair – confirm on headset',
    'Bestehende Verbindung prüfen': 'Check existing connection',
    'Koppeln nutzt Valves vorhandenen SSH-Schlüssel. Beim Prüfen werden wie im Valve Client die Devkit-Hilfsdateien aktualisiert.': 'Pairing uses Valve’s existing SSH key. Checking the connection also updates Devkit helper files, as the Valve client does.',
    'Weiter: Chromium installieren': 'Next: Install Chromium',
    'Browser vorbereiten': 'Prepare browser',
    'Download direkt aus Googles Chromium-Snapshot-Archiv: Android_Arm64 → ChromePublic.apk. Snapshots erhalten keine automatischen Updates; neue Revisionen werden nur auf deinen Klick geladen. Für H.264/AAC-Videos eine passende vollständige Chrome-/Chromium-APK lokal auswählen; der Standard-Snapshot unterstützt diese Codecs nicht. OpenXR und Videowiedergabe müssen am Frame geprüft werden.': 'Download the official Chromium snapshot from Google: Android_Arm64 → ChromePublic.apk. Snapshots do not update automatically; download a new revision when you choose. For H.264/AAC video, select a compatible full Chrome/Chromium APK. The default snapshot does not include these codecs. Check OpenXR and video playback on Frame.',
    'Flatscreen-Marker für Browseroberfläche verwenden (experimentell)': 'Use flatscreen marker for browser display (experimental)',
    'VR-Berechtigung automatisch erlauben (Abfrage umgehen)': 'Automatically allow VR permission (skip prompt)',
    'Vermeidet den Absturz bei der ersten VR-Freigabe. Sichere Webseiten erhalten beim VR-Einstieg automatisch Zugriff auf Kopf- und Controllerbewegungen. Änderungen nach erneutem Übertragen und Browserstart aktiv; deaktiviert wird wieder gefragt.': 'Skips the initial VR permission prompt. Secure websites automatically receive access to head and controller movement when entering VR. Changes take effect after transferring the title again and restarting the browser. When disabled, the browser asks again.',
    'VR-Grafikvorbereitung automatisch im Steam-Titel starten': 'Automatically prepare VR graphics when the Steam title starts',
    'Nach dem Übertragen und Neustart des Steam-Titels auch ohne PC aktiv: beliebige sichere WebXR-Seiten am Headset öffnen. Neue Tabs und Neuladen erhalten die Grafikvorbereitung automatisch.': 'After transferring and restarting the Steam title, this works without the PC: open any secure WebXR page on the headset. New tabs and reloads are prepared automatically.',
    'Offiziellen ARM64-Chromium herunterladen': 'Download official ARM64 Chromium',
    'Lokale ARM64-Browser-APK auswählen …': 'Choose local ARM64 browser APK …',
    'Noch keine APK vorbereitet.': 'No APK prepared yet.',
    'Auf das gekoppelte Frame übertragen': 'Transfer to paired Frame',
    'Devkit-Titel: ': 'Devkit title: ',
    '\nStarthelfer: launch-chromium.sh → Lepton (Android)\nEin erneuter Upload aktualisiert denselben Titel.': '\nLauncher: launch-chromium.sh → Lepton (Android)\nUploading again updates the same title.',
    'Experimentelle Lepton-Anpassung für Chromium: behebt den Start der Seitenprozesse und ergänzt den benötigten Android-Dienst. Bitte vorerst nur vertrauenswürdige XR-Testseiten verwenden.': 'Experimental Lepton integration for Chromium: supports renderer startup and provides a required Android service. Use trusted XR pages.',
    'Chromium aufs Frame übertragen': 'Transfer Chromium to Frame',
    'Chromium am Frame starten': 'Start Chromium on Frame',
    'Weiter: XR testen': 'Next: XR tools',
    'OpenXR im Browser aktivieren': 'Enable OpenXR in the browser',
    'Im Chromium am Headset:\n\nchrome://flags/#enable-openxr-android → Enabled\nchrome://flags/#webxr-runtime → OpenXR\n\nMit „Relaunch“ übernehmen, anschließend Chromium bei Bedarf über diese App wieder starten. Bei „Google Play services / Device not compatible“ ist meist Cardboard aktiv: beide OpenXR-Einstellungen prüfen. Fehlen die Flags, ist dieser Build nicht als XR-fähig bestätigt.': 'In Chromium on the headset:\n\nchrome://flags/#enable-openxr-android → Enabled\nchrome://flags/#webxr-runtime → OpenXR\n\nApply with “Relaunch”, then restart Chromium from this app if needed. If you see “Google Play services / Device not compatible”, Cardboard may be active; check both OpenXR settings. If the flags are missing, this build may not support XR.',
    'WebXR-Testseite im Frame-Browser öffnen': 'Open WebXR check page in Frame browser',
    'Controller-Testseite im Frame-Browser öffnen': 'Open controller check page in Frame browser',
    'Beim Controller-Test „Enter VR“ wählen. Tasten ändern die Farbe der Kästchen; Sticks bewegen sie. Beide Controller prüfen.': 'On the controller page, choose “Enter VR”. Buttons change the boxes’ colors; sticks move them. Check both controllers.',
    'Browser und WebXR automatisch prüfen': 'Check browser and WebXR automatically',
    'Android-Netzwerk und Seitenprozesse prüfen': 'Check Android network and renderer processes',
    'WebXR-Seite mit vorbereiteter Grafik': 'WebXR page with prepared graphics',
    'Bereitet die Grafik bereits beim Laden für den VR-Einstieg vor. Hilft bei Seiten, deren Grafik erst zu spät für VR eingerichtet wird.': 'Prepares graphics while the page loads, before entering VR. This helps pages that otherwise prepare graphics too late.',
    'https://… – beliebige WebXR-Zieladresse': 'https://… – any WebXR page',
    'Mit VR-Grafikvorbereitung öffnen': 'Open with VR graphics preparation',
    'Optionaler Start vom PC: öffnet deine Zieladresse in einem frischen Android-Browser-Tab und schließt ihre früheren Tabs. Am Headset „Enter VR“ wählen.\n\nMit aktivierter automatischer Vorbereitung im Steam-Titel kannst du die Adresse direkt am Headset öffnen; dieser Knopf ist dann nicht erforderlich. Nach einem Hänger den Steam-Titel vollständig beenden und neu starten.': 'Optional: open the selected address from the PC in a new Android browser tab; earlier tabs for that address are closed. Choose “Enter VR” on the headset.\n\nWhen automatic preparation is enabled in the Steam title, open the address directly on the headset instead. If the title stops responding, quit it fully and restart it.',
    'Testergebnis': 'Results',
    'Die immersive Sitzung zeigt die VR-Szene korrekt an': 'The immersive session displays the VR scene correctly',
    'Controller-Eingabe funktioniert in der VR-Sitzung': 'Controller input works in the VR session',
    'Erfolgreichen Gerätetest festhalten': 'Record successful device check',
    'Fehler beim VR-Versuch beschreiben …': 'Describe the VR issue …',
    'Fehlgeschlagenen VR-Versuch festhalten': 'Record unsuccessful VR check',
    'Der Devkit-Port muss eine Zahl sein.': 'The Devkit port must be a number.',
    'Der Devkit-Port muss zwischen 1 und 65535 liegen.': 'The Devkit port must be between 1 and 65535.',
    'Ziel geändert. Bitte Verbindung erneut prüfen.': 'Target changed. Check the connection again.',
    'Noch nicht übertragen': 'Not transferred',
    'Noch nicht geprüft': 'Not checked',
    'Noch nicht getestet': 'Not tested',
    'Noch nicht installiert': 'Not installed',
    'Installation': 'Installation',
    'Browser': 'Browser',
    'WebXR-Unterstützung': 'WebXR support',
    'Immersive VR': 'Immersive VR',
    'Noch keine Geräte gesucht': 'No devices found yet',
    'Gerät auswählen …': 'Select a device …',
    'Voraussetzungen prüfen …': 'Checking requirements …',
    'Frame im Netzwerk suchen …': 'Searching for Frame on the network …',
    'Kopplungsanfrage läuft – bitte am Headset bestätigen.': 'Pairing request sent – confirm it on the headset.',
    'SSH-Verbindung und Frame prüfen …': 'Checking SSH connection and Frame …',
    'Chromium herunterladen und prüfen …': 'Downloading and checking Chromium …',
    'APK prüfen …': 'Checking APK …',
    'Chromium übertragen …': 'Transferring Chromium …',
    'Start am Frame anfordern …': 'Requesting start on Frame …',
    'ADB-Plattformwerkzeuge herunterladen …': 'Downloading ADB platform tools …',
    'WebXR-Testseite öffnen …': 'Opening WebXR check page …',
    'Controller-Testseite öffnen …': 'Opening controller check page …',
    'WebXR-Zieladresse laden und Grafik für VR vorbereiten …': 'Loading WebXR page and preparing graphics for VR …',
    'Browser und WebXR prüfen …': 'Checking browser and WebXR …',
    'Android-Netzwerk und Seitenprozesse prüfen …': 'Checking Android network and renderer processes …',
    'Zuerst eine APK vorbereiten.': 'Prepare an APK first.',
    'Bitte die Kopplungsanfrage jetzt am Headset bestätigen.': 'Confirm the pairing request on the headset now.',
    'Aktion fehlgeschlagen.': 'Action failed.',
    'Automatische Prüfung nicht verfügbar – manuellen Test durchführen': 'Automatic check unavailable – perform a manual check',
    'Voraussetzungen geprüft.': 'Requirements checked.',
    ' Alle erforderlichen Programme gefunden.': ' All required programs were found.',
    ' Fehlende Programme: ': ' Missing programs: ',
    'FEHLT': 'MISSING',
    'Devkit Client: ': 'Devkit Client: ',
    '\nADB: ': '\nADB: ',
    'Noch nicht installiert': 'Not installed',
    'Gerät(e) gefunden. Bei Bedarf Hostname/IP manuell eingeben.': 'device(s) found. Enter a hostname/IP manually if needed.',
    'Verbunden mit Steam Frame: ': 'Connected to Steam Frame: ',
    ' · SSH als ': ' · SSH user: ',
    'Steam Frame verbunden. Chromium kann vorbereitet und übertragen werden.': 'Connected to Steam Frame. Chromium can now be prepared and transferred.',
    'Vorhandener Titel: APK und Starthelfer per SHA-256 bestätigt': 'Existing title: APK and launcher verified by SHA-256',
    'Steam Frame verbunden. Der vorhandene Chromium-Titel wurde geprüft und kann gestartet werden.': 'Connected to Steam Frame. The existing Chromium title is ready to start.',
    'Steam Frame verbunden. Den Titel erneut übertragen; APK und Starthelfer wurden nicht als übereinstimmend bestätigt.': 'Connected to Steam Frame. Transfer the title again; the APK and launcher did not match.',
    'ARM64-APK geprüft und für den Upload vorbereitet.': 'ARM64 APK checked and ready to transfer.',
    'Übertragen und Devkit-Titel auf dem Frame gefunden': 'Transferred and Devkit title found on Frame',
    'Upload abgeschlossen. Den Steam-Titel am Frame starten; läuft er bereits, vollständig beenden und neu starten.': 'Transfer complete. Start the Steam title on Frame; if it is already running, quit it fully and restart.',
    'Läuft – Android-Prozess über ADB bestätigt': 'Running – Android process confirmed through ADB',
    'Chromium läuft. Browseroberfläche am Headset prüfen und XR-Flags einstellen.': 'Chromium is running. Check the browser on the headset and set the XR flags.',
    'Start angefordert – Browserprozess nicht bestätigt': 'Start requested – browser process not confirmed',
    'Start angefordert. Browseroberfläche bitte am Headset prüfen.': 'Start requested. Check the browser on the headset.',
    'ADB-Plattformwerkzeuge bereit. Lepton muss für die Diagnose am Frame laufen.': 'ADB platform tools are ready. Lepton must be running on Frame for diagnostics.',
    'WebXR-Testseite angefordert. Nach dem Laden automatisch prüfen oder „Enter VR“ am Headset wählen.': 'WebXR check page requested. Run the automatic check after it loads or choose “Enter VR” on the headset.',
    'Controller-Testseite angefordert. Am Headset „Enter VR“ wählen und Tasten sowie Sticks beider Controller prüfen.': 'Controller check page requested. Choose “Enter VR” on the headset and check the buttons and sticks on both controllers.',
    'Die WebXR-Seite ist mit für VR vorbereiteter Grafik geladen. Am Headset „Enter VR“ wählen; anschließend Darstellung und Controller testen.': 'The WebXR page loaded with graphics prepared for VR. Choose “Enter VR” on the headset, then check the display and controllers.',
    'Die VR-Grafikvorbereitung ist für diese Seite eingerichtet. Ihr Grafikkontext entsteht erst bei weiterer Bedienung. Am Headset „Enter VR“ wählen und testen.': 'VR graphics preparation is set up for this page. Its graphics context will be created after further interaction. Choose “Enter VR” on the headset to check it.',
    'OK': 'OK',
    'fehlgeschlagen': 'failed',
    'läuft': 'running',
    'Prüfen': 'Check',
    'Chromium': 'Chromium',
    'Paket: ': 'Package: ',
    'Release: ': 'Release: ',
    'Revision: ': 'Revision: ',
    'Startaktivität: ': 'Launch activity: ',
    'Starthelfer: ': 'Launcher: ',
    'Quelle: ': 'Source: ',
    'SHA-256: ': 'SHA-256: ',
    'OpenXR-Hinweise in APK: ': 'OpenXR evidence in APK: ',
    'gefunden; Gerätetest offen': 'found; device check pending',
    'nicht vollständig nachgewiesen': 'not fully verified',
    'Zieladresse': 'target address',
    'WebXR-Zieladresse': 'WebXR target address',
    'Nicht verbunden: ': 'Not connected: ',
    'Verbunden mit Steam Frame: ': 'Connected to Steam Frame: ',
    'Der Hintergrundprozess konnte nicht gestartet werden. Python-Umgebung prüfen.': 'Could not start the background process. Check the Python environment.',
    'Aktion abgebrochen. Bei einem Upload kann eine Teilübertragung vorliegen; erneut übertragen.': 'Action cancelled. A transfer may be incomplete; transfer the title again.',
    'Abbruch läuft …': 'Cancelling …',
    'Aktion abgebrochen. Bei einem Upload kann eine Teilübertragung vorliegen; erneut übertragen.': 'Action cancelled. A transfer may be incomplete; transfer the title again.',
    'Zeitlimit überschritten. Prozess wird abgebrochen.': 'Timed out. Stopping the process.',
    'Bitte die WebXR-Zieladresse ohne Leerzeichen eingeben.': 'Enter a WebXR target address without spaces.',
    'Der Devkit-Port muss eine Zahl sein.': 'The Devkit port must be a number.',
    'Installierten SteamOS Devkit Client in Steam geöffnet.': 'Opened the installed SteamOS Devkit Client in Steam.',
    'Steam konnte nicht geöffnet werden. Devkit Client in Steam → Werkzeuge starten.': 'Could not open Steam. Start the Devkit Client from Steam → Tools.',
    'Installation in Steam abschließen. Die App erkennt den Client anschließend automatisch.': 'Finish installing in Steam. The app will detect the client automatically.',
    'Steam konnte nicht geöffnet werden. SteamOS Devkit Client in Steam → Werkzeuge installieren.': 'Could not open Steam. Install the SteamOS Devkit Client from Steam → Tools.',
    'Vollständige ARM64-Browser-APK auswählen': 'Select a full ARM64 browser APK',
    'Android APK (*.apk)': 'Android APK (*.apk)',
    'Erfolgreicher VR-Gerätetest festgehalten.': 'Successful VR device check recorded.',
    'Bitte den beobachteten VR-Fehler beschreiben.': 'Describe the observed VR issue.',
    'Fehlgeschlagenen VR-Versuch festgehalten.': 'Unsuccessful VR check recorded.',
    'Diagnoseprotokoll speichern': 'Save diagnostic report',
    'JSON (*.json)': 'JSON (*.json)',
    'Diagnoseprotokoll gespeichert: ': 'Diagnostic report saved: ',
    'Protokoll konnte nicht gespeichert werden: ': 'Could not save report: ',
    'Letzte bestätigte Geräteabnahme: ': 'Last confirmed device check: ',
    '\nVR-Darstellung und beide Controller vom Nutzer bestätigt. Die aktuellen Laufzeitprüfungen stehen darunter.': '\nThe user confirmed the VR display and both controllers. Current runtime checks are shown below.',
    'Am Headset vom Nutzer bestätigt: Darstellung und Controller funktionieren': 'Confirmed by the user on the headset: display and controllers work',
    'Fehlgeschlagen: ': 'Failed: ',
    'Läuft: ': 'Running: ',
    'Browser läuft, aber Seitenprozesse scheitern an Lepton': 'Browser is running, but renderer processes fail under Lepton',
    'Nicht prüfbar – Chromium-Seitenprozesse starten nicht': 'Could not check – Chromium renderer processes did not start',
    'immersive-vr wird unterstützt': 'immersive-vr is supported',
    'immersive-vr wird nicht unterstützt': 'immersive-vr is not supported',
    'WebXR geprüft. OpenXR-Flags am Headset prüfen; auch Cardboard kann immersive-vr melden. Die tatsächliche VR-Sitzung und Controller müssen am Headset getestet werden.': 'WebXR checked. Verify the OpenXR flags on the headset; Cardboard can also report immersive-vr. Check the actual VR session and controllers on the headset.',
    'Falls die Debugschnittstelle fehlt: Testseite im Chromium am Headset öffnen und „Enter VR“ drücken.\nDarstellung: ': 'If the debugging interface is unavailable, open the check page in Chromium on the headset and press “Enter VR”.\nDisplay: ',
    '\nController-Eingabe: ': '\nController input: ',
    '\n\nOptional über eine Browserkonsole: navigator.xr.isSessionSupported("immersive-vr"). Ein true bestätigt noch keine funktionierende VR-Sitzung.': '\n\nOptional, in the browser console: navigator.xr.isSessionSupported("immersive-vr"). A true result does not confirm a working VR session.',
    'Manueller Test durchführen': 'Perform a manual check',
    'Nicht installiert': 'Not installed',
    'Übertragen': 'Transferred',
    'Noch nicht geprüft': 'Not checked',
    'Noch nicht getestet': 'Not tested',
    'Noch nicht übertragen': 'Not transferred',
    'Noch keine Verbindung geprüft.': 'Connection has not been checked yet.',
    'Installierten SteamOS Devkit Client in Steam geöffnet.': 'Opened the installed SteamOS Devkit Client in Steam.',
    'Voraussetzungen geprüft.': 'Requirements checked.',
    'Hintergrundprozess beendet ohne Ergebnis (Code ': 'Background process exited without a result (code ',
    '). Details im Protokoll.': '). See the log for details.',
    'WebXR-Unterstützung': 'WebXR support',
    '\nStartaktivität: ': '\nLaunch activity: ',
    ' Devkit-Gerät(e) gefunden. Bei Bedarf Hostname/IP manuell eingeben.': ' Devkit device(s) found. Enter a hostname/IP manually if needed.',
    'Geräteabnahme konnte nicht gespeichert werden: ': 'Could not save device check: ',
    'Spracheinstellung konnte nicht gespeichert werden: ': 'Could not save language preference: ',
    'bitte APK erneut vorbereiten': 'prepare the APK again',
    '[SSH-Schlüssel entfernt]': '[SSH key removed]',
    '[privater Schlüssel entfernt]': '[private key removed]',
    'Lepton-ADB direkt über %s (überlappende VPN-Route umgangen)': 'Lepton ADB directly via %s (overlapping VPN route bypassed)',
    'Frame-Verbindung direkt über %s (überlappende VPN-Route umgangen)': 'Frame connection directly via %s (overlapping VPN route bypassed)',
    'SteamOS Devkit Client in Steam öffnen': 'Open SteamOS Devkit Client in Steam',
    'SSH und rsync fehlen? Arch: sudo pacman -S openssh rsync · Debian: sudo apt install openssh-client rsync': 'Missing SSH and rsync? Arch: sudo pacman -S openssh rsync · Debian: sudo apt install openssh-client rsync',
    'Chromiums Debugschnittstelle antwortet nicht rechtzeitig. Testseite am Headset vollständig laden lassen, eine offene Browser-Freigabe bestätigen und die Prüfung wiederholen.': 'Chromium’s debugging interface did not respond in time. Let the page finish loading on the headset, confirm any open browser permission prompt, and try again.',
    'Die APK wurde nach der Prüfung verändert; bitte erneut vorbereiten.': 'The APK changed after validation; prepare it again.',
    'Frame lehnt die Anfrage ab (HTTP 403). Am Headset Einstellungen → Entwickler → Neuen Host koppeln öffnen und erneut koppeln.': 'Frame rejected the request (HTTP 403). On the headset, open Settings → Developer → Pair New Host and pair again.',
    'Hostname nicht auflösbar. Bitte die WLAN-IP des Frames eingeben.': 'Could not resolve the hostname. Enter Frame’s Wi-Fi IP address.',
    'SSH-Anmeldung abgelehnt. Bitte am Frame „Neuen Host koppeln“ öffnen und die Kopplungsanfrage bestätigen.': 'SSH login was rejected. Open “Pair New Host” on Frame and confirm the pairing request.',
    'SSH-Sitzung konnte nicht aufgebaut werden. Entwicklermodus und Kopplung am Frame prüfen. Details: ': 'Could not establish an SSH session. Check Developer Mode and pairing on Frame. Details: ',
    'Zeitüberschreitung. Netzwerk/IP prüfen und sicherstellen, dass der Devkit-Dienst bzw. Lepton am Frame läuft.': 'Connection timed out. Check the network/IP and make sure the Devkit service or Lepton is running on Frame.',
    'APK im Archiv ist unerwartet groß.': 'The APK in the archive is unexpectedly large.',
    'Chromium liefert keine gültige Snapshot-Revision.': 'Chromium returned an invalid snapshot revision.',
    'Die APK enthält keine nativen ARM64-Bibliotheken.': 'The APK contains no native ARM64 libraries.',
    'Die Browser-APK enthält keine startbare MAIN/LAUNCHER-Aktivität.': 'The browser APK contains no launchable MAIN/LAUNCHER activity.',
    'Download ist unerwartet groß (über 1 GiB).': 'The download is unexpectedly large (over 1 GiB).',
    'Download unvollständig: ': 'Incomplete download: ',
    'Download überschreitet 1 GiB.': 'The download exceeds 1 GiB.',
    'Eine ARM64-Bibliothek enthält keinen gültigen AArch64-ELF-Header.': 'An ARM64 library has an invalid AArch64 ELF header.',
    'Keine gültige vollständige Android-APK mit Manifest.': 'No valid complete Android APK with a manifest was found.',
    'Offizielles Archiv enthält keine eindeutige ChromePublic.apk.': 'The official archive does not contain a unique ChromePublic.apk.',
    'Split-APKs werden nicht unterstützt; eine vollständige Browser-APK auswählen.': 'Split APKs are not supported. Select a complete browser APK.',
    'Ungültige WebXR-Zieladresse.': 'Invalid WebXR target address.',
    'Ungültiger Activity-Name im Android-Manifest.': 'Invalid activity name in the Android manifest.',
    'Ungültiger Paketname im Manifest.': 'Invalid package name in the manifest.',
    'Ungültiger Pfad im ADB-Archiv.': 'Invalid path in the ADB archive.',
    'WebXR benötigt eine HTTPS-Zieladresse; HTTP ist nur für localhost möglich.': 'WebXR requires an HTTPS address; HTTP is only allowed for localhost.',
    'Das verbundene Gerät wurde nicht als Steam Frame erkannt. Bitte Firmware und Zieladresse prüfen.': 'The connected device was not identified as a Steam Frame. Check its firmware and address.',
    'Die APK enthält keine startbare Launcher-Aktivität. Bitte erneut vorbereiten.': 'The APK has no launchable activity. Prepare it again.',
    'Ungültiger Devkit-Port.': 'Invalid Devkit port.',
    '\nTestseite im Chromium am Headset öffnen: ': '\nOpen the page in Chromium on the headset: ',
    'Am gewählten ADB-Endpunkt läuft kein Android-Container.': 'No Android container is running at the selected ADB endpoint.',
    'Bitte zuerst „WebXR-Testseite öffnen“ klicken und die Seite im Headset laden lassen.': 'First choose “Open WebXR check page” and let the page load on the headset.',
    'Chromium hat keinen Tab für die Testseite angelegt.': 'Chromium did not create a tab for the check page.',
    'Chromium hat keinen Tab für die Zieladresse angelegt.': 'Chromium did not create a tab for the target address.',
    'Chromium liefert kein verwertbares XR-Prüfergebnis.': 'Chromium returned no usable XR check result.',
    'Chromium läuft, aber Lepton verhindert den Start seiner isolierten Seitenprozesse (setresgid). Webseiten und WebXR sind damit nicht funktionsfähig. „Android-Netzwerk und Seitenprozesse prüfen“ liefert die getrennte Diagnose.': 'Chromium is running, but Lepton could not start its isolated renderer processes (setresgid). Websites and WebXR are unavailable. Choose “Check Android network and renderer processes” for details.',
    'Chromium läuft, aber seine Debugschnittstelle ist nicht eindeutig verfügbar. Bitte den manuellen XR-Test verwenden.': 'Chromium is running, but its debugging interface could not be identified. Use the manual XR check.',
    'Der bisherige Tab dieser Zieladresse konnte nicht beendet werden. Bitte am Headset schließen und wiederholen.': 'Could not close the previous tab for this address. Close it on the headset and try again.',
    'Der vorbereitete Browser läuft im Lepton-Container nicht. Bitte am Frame starten.': 'The prepared browser is not running in the Lepton container. Start it on Frame.',
    'Die Debugschnittstelle gehört nicht zum vorbereiteten Android-Browser.': 'The debugging interface does not belong to the prepared Android browser.',
    'Die Grafik konnte nicht für VR vorbereitet werden. Bitte Browser neu starten und wiederholen.': 'Could not prepare graphics for VR. Restart the browser and try again.',
    'Die WebXR-Testseite ist noch nicht vollständig geladen oder zeigt einen Ladefehler. Bitte am Headset prüfen und erneut testen.': 'The WebXR page has not finished loading or shows a loading error. Check it on the headset and try again.',
    'Die Zieladresse wurde nicht rechtzeitig mit VR-Grafikvorbereitung geladen. Bitte am Headset prüfen und wiederholen.': 'The page did not load with VR graphics preparation in time. Check it on the headset and try again.',
    'Die Zieladresse zeigt einen Ladefehler. Internetverbindung am Frame prüfen.': 'The page shows a loading error. Check Frame’s internet connection.',
    'Lepton verhindert den Start isolierter Chromium-Seitenprozesse (setresgid). Dadurch bleiben Webseiten leer, obwohl der Container Internet hat. Diese Chromium-/Lepton-Kombination ist nicht als funktionsfähig bestätigt.': 'Lepton could not start Chromium’s isolated renderer processes (setresgid). Pages may remain blank even when the container has internet access. This Chromium/Lepton combination has not been confirmed to work.',
    'Lepton-ADB ist nicht erreichbar. Zuerst „Chromium am Frame starten“ ausführen. Falls der Browser sofort schließt, liegt ein Startfehler vor. Details: ': 'Lepton ADB is unavailable. First choose “Start Chromium on Frame”. If the browser closes immediately, it failed to start. Details: ',
    'Start angefordert, aber Chromium wurde über ADB nicht als laufend bestätigt. Browserbild am Headset prüfen; gegebenenfalls erneut starten. ': 'Start was requested, but ADB did not confirm Chromium is running. Check the headset display and retry if needed. ',
    'Ungültige Chromium-Debugadresse.': 'Invalid Chromium debugging address.',
    'Ungültiger ADB-Port.': 'Invalid ADB port.',
    'Ungültiger Android-Paketname.': 'Invalid Android package name.',
    'WebXR-Prüfung meldet: ': 'WebXR check reported: ',
}


def translate(value: str) -> str:
    value = str(value)
    if LANGUAGE == 'de':
        return value
    if value in ENGLISH:
        return ENGLISH[value]
    # Translate reusable fragments in dynamic status and error messages.
    fragments = (
        ('Paket:', 'Package:'),
        ('Release:', 'Release:'),
        ('Revision:', 'Revision:'),
        ('Startaktivität:', 'Launch activity:'),
        ('Starthelfer:', 'Launcher:'),
        ('Quelle:', 'Source:'),
        ('OpenXR-Hinweise in APK:', 'OpenXR evidence in APK:'),
        ('FEHLT', 'MISSING'),
        ('Devkit Client:', 'Devkit Client:'),
        ('ADB:', 'ADB:'),
        (' · SSH als ', ' · SSH user: '),
        ('Letzte bestätigte Geräteabnahme:', 'Last confirmed device check:'),
        ('Spracheinstellung konnte nicht gespeichert werden:', 'Could not save language preference:'),
        ('VR-Darstellung und beide Controller vom Nutzer bestätigt. Die aktuellen Laufzeitprüfungen stehen darunter.', 'The user confirmed the VR display and both controllers. Current runtime checks are shown below.'),
        ('Start angefordert, aber Chromium wurde über ADB nicht als laufend bestätigt.', 'Start was requested, but ADB did not confirm Chromium is running.'),
        ('Browserbild am Headset prüfen; gegebenenfalls erneut starten.', 'Check the headset display; retry if needed.'),
        ('Die WebXR-Testseite ist noch nicht vollständig geladen', 'The WebXR page has not finished loading'),
        ('Bitte am Headset prüfen und erneut testen.', 'Check it on the headset and try again.'),
        ('Noch nicht übertragen', 'Not transferred'),
        ('Noch nicht geprüft', 'Not checked'),
        ('Noch nicht getestet', 'Not tested'),
        ('Nicht verbunden:', 'Not connected:'),
        ('Verbunden mit Steam Frame:', 'Connected to Steam Frame:'),
        ('Gerät(e) gefunden.', 'device(s) found.'),
        ('Bei Bedarf Hostname/IP manuell eingeben.', 'Enter a hostname/IP manually if needed.'),
        ('Läuft:', 'Running:'),
        ('Fehlgeschlagen:', 'Failed:'),
        ('Steam Frame verbunden.', 'Connected to Steam Frame.'),
        ('Bitte ', 'Please '),
        ('prüfen.', 'check.'),
        ('Prüfen', 'Check'),
        ('Fehler', 'Error'),
    )
    for source, target in fragments:
        value = value.replace(source, target)
    return value


def translate_log_line(value: str) -> str:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return translate(value)

    def localize(item):
        if isinstance(item, str):
            return translate(item)
        if isinstance(item, list):
            return [localize(child) for child in item]
        if isinstance(item, dict):
            return {key: localize(child) for key, child in item.items()}
        return item

    return json.dumps(localize(parsed), ensure_ascii=False)


class LocalizedLabel(QLabel):
    def __init__(self, text='', *args, **kwargs):
        super().__init__('', *args, **kwargs)
        self.setText(text)

    def setText(self, text):
        self._source_text = str(text)
        super().setText(translate(self._source_text))

    def retranslate(self):
        super().setText(translate(self._source_text))


class LocalizedButton(QPushButton):
    def __init__(self, text='', *args, **kwargs):
        super().__init__('', *args, **kwargs)
        self.setText(text)

    def setText(self, text):
        self._source_text = str(text)
        super().setText(translate(self._source_text))

    def retranslate(self):
        super().setText(translate(self._source_text))


class LocalizedCheckBox(QCheckBox):
    def __init__(self, text='', *args, **kwargs):
        super().__init__('', *args, **kwargs)
        self.setText(text)

    def setText(self, text):
        self._source_text = str(text)
        super().setText(translate(self._source_text))

    def retranslate(self):
        super().setText(translate(self._source_text))


class LocalizedGroupBox(QGroupBox):
    def __init__(self, title='', *args, **kwargs):
        super().__init__('', *args, **kwargs)
        self.setTitle(title)

    def setTitle(self, title):
        self._source_title = str(title)
        super().setTitle(translate(self._source_title))

    def retranslate(self):
        super().setTitle(translate(self._source_title))


class LocalizedLineEdit(QLineEdit):
    def setPlaceholderText(self, text):
        self._source_placeholder = str(text)
        super().setPlaceholderText(translate(self._source_placeholder))

    def retranslate(self):
        if hasattr(self, '_source_placeholder'):
            super().setPlaceholderText(translate(self._source_placeholder))


class LocalizedPlainTextEdit(QPlainTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._source_lines = []

    def appendPlainText(self, text):
        text = str(text)
        self._source_lines.append(text)
        self._source_lines = self._source_lines[-4000:]
        super().appendPlainText(translate_log_line(text))

    def retranslate(self):
        super().clear()
        for line in self._source_lines:
            super().appendPlainText(translate_log_line(line))
