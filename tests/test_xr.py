import json
from contextlib import nullcontext
import io
import shutil
import subprocess
from types import SimpleNamespace
import pytest
from frame_apk_push import xr


@pytest.mark.parametrize('failure', ['none', 'connect', 'operation'])
def test_vpn_adb_uses_lan_and_cleans_only_its_endpoint(monkeypatch, failure):
    monkeypatch.setattr(xr.network, 'local_interface', lambda host: 'wlan0')
    relays = []
    def relay(*args, **kwargs):
        relays.append(args)
        return nullcontext(54321)
    monkeypatch.setattr(xr.network, 'lan_tcp_forward', relay)
    connects = []
    def connect(host, **kwargs):
        connects.append((host, kwargs))
        if failure == 'connect':
            raise RuntimeError('Android check failed')
        return 'adb', f'{host}:{kwargs["port"]}'
    monkeypatch.setattr(xr, 'open_adb', connect)
    monkeypatch.setattr(xr.shutil, 'which', lambda name: 'adb')
    monkeypatch.setattr(xr, 'adb_path', lambda: type('Missing', (), {'is_file': lambda self: False})())
    commands = []
    monkeypatch.setattr(xr.subprocess, 'run', lambda args, **kwargs: commands.append(args))
    if failure == 'none':
        with xr.adb_connection('frame') as connection:
            assert connection == ('adb', '127.0.0.1:54321')
    else:
        with pytest.raises(RuntimeError):
            with xr.adb_connection('frame'):
                raise RuntimeError('CDP failed')
    assert connects == [('127.0.0.1', {'port': 54321})]
    assert relays == [('frame', 5555, 'wlan0')]
    assert commands == [['adb', 'disconnect', '127.0.0.1:54321']]


def test_adb_without_overlapping_route_uses_existing_endpoint(monkeypatch):
    monkeypatch.setattr(xr.network, 'local_interface', lambda host: None)
    calls = []
    monkeypatch.setattr(xr, 'open_adb', lambda host: calls.append(host) or ('adb', 'frame:5555'))
    def unexpected(*args, **kwargs):
        raise AssertionError('No relay or disconnect for a direct connection')
    monkeypatch.setattr(xr.network, 'lan_tcp_forward', unexpected)
    monkeypatch.setattr(xr.subprocess, 'run', unexpected)
    with xr.adb_connection('frame') as connection:
        assert connection == ('adb', 'frame:5555')
    assert calls == ['frame']


def test_local_adb_relay_port_is_used_for_connect_and_android_check(monkeypatch):
    monkeypatch.setattr(xr.shutil, 'which', lambda name: 'adb')
    monkeypatch.setattr(xr, 'adb_path', lambda: type('Missing', (), {'is_file': lambda self: False})())
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='connected to 127.0.0.1:54321', stderr='')
    monkeypatch.setattr(xr.subprocess, 'run', run)
    checks = []
    monkeypatch.setattr(xr, 'run_adb', lambda *args, **kwargs: checks.append(args) or '30')
    assert xr.open_adb('127.0.0.1', port=54321) == ('adb', '127.0.0.1:54321')
    assert calls == [['adb', 'connect', '127.0.0.1:54321']]
    assert checks[0][1] == '127.0.0.1:54321'


def test_cdp_ignores_events_and_unrelated_responses():
    class WS:
        def send(self, data): self.id = json.loads(data)['id']; self.count = 0
        def settimeout(self, timeout): pass
        def recv(self):
            self.count += 1
            if self.count == 1: return '{"method":"Runtime.consoleAPICalled"}'
            return json.dumps({'id': self.id, 'result': {'result': {'value': True}}})
    assert xr.cdp_call(WS(), 'Runtime.evaluate')['result']['value'] is True


def test_cdp_error():
    class WS:
        def send(self, data): self.id = json.loads(data)['id']
        def settimeout(self, timeout): pass
        def recv(self): return json.dumps({'id': self.id, 'error': {'message': 'permission denied'}})
    with pytest.raises(RuntimeError, match='permission denied'):
        xr.cdp_call(WS(), 'Runtime.evaluate')


def test_missing_debug_socket_uses_manual_test(monkeypatch):
    ticks = iter((0, 10))
    monkeypatch.setattr(xr.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(xr, 'open_adb', lambda host: ('adb', 'frame:5555'))
    def adb(*args, **kwargs):
        return '123' if 'pidof' in args else 'not a chromium socket'
    monkeypatch.setattr(xr, 'run_adb', adb)
    with pytest.raises(xr.ManualTestRequired):
        xr.diagnose('frame', 'org.chromium.chrome')


@pytest.mark.parametrize('names', [
    ['chrome_devtools_remote', 'chrome_devtools_remote'],
    ['chrome_devtools_remote_123', 'chrome_devtools_remote_123'],
    ['chrome_devtools_remote', 'chrome_devtools_remote_123']])
def test_native_helper_socket_connections_are_deduplicated_but_distinct_browsers_rejected(monkeypatch, names):
    commands = []
    def adb(*args, **kwargs):
        commands.append(args[2:])
        if 'pidof' in args: return '123'
        if '/proc/net/unix' in args: return '\n'.join('socket @' + name for name in names)
        if 'tcp:0' in args: return '54321'
        return ''
    monkeypatch.setattr(xr, 'run_adb', adb)
    monkeypatch.setattr(xr.urllib.request, 'urlopen', lambda *a, **k:
        io.BytesIO(b'{"Android-Package":"com.android.chrome"}'))
    if len(set(names)) > 1:
        with pytest.raises(xr.ManualTestRequired, match='nicht eindeutig'):
            with xr._browser_debug_connected('adb', 'frame:5555', 'com.android.chrome'): pass
        assert not any(command[0] == 'forward' for command in commands)
    else:
        with xr._browser_debug_connected('adb', 'frame:5555', 'com.android.chrome') as (base, _):
            assert base == 'http://127.0.0.1:54321'
        assert ('forward', 'tcp:0', 'localabstract:' + names[0]) in commands
        assert commands[-1] == ('forward', '--remove', 'tcp:54321')


def test_network_works_but_renderer_start_fails(monkeypatch):
    monkeypatch.setattr(xr, 'open_adb', lambda host: ('adb', 'frame:5555'))
    def adb(*args, **kwargs):
        if 'ps' in args:
            return 'root 123 0 org.chromium.chrome'
        if 'logcat' in args:
            return 'F m.chrome_zygot: setresgid(90000) failed: Invalid argument'
        if any('curl ' in str(arg) for arg in args):
            return '200'
        return '1 packets transmitted, 1 received'
    monkeypatch.setattr(xr, 'run_adb', adb)
    result = xr.network_diagnose('frame', 'org.chromium.chrome')
    assert all(check['ok'] for check in result['network'].values())
    assert result['browser_running'] and result['renderer_failed']
    assert 'obwohl der Container Internet hat' in result['message']


def test_renderer_failure_is_specific_to_chromium():
    assert not xr.renderer_failure('otherapp: setresgid(90000) failed: Invalid argument')
    assert not xr.renderer_failure('chromium: unrelated warning')


def test_start_waits_for_browser_after_container_becomes_available(monkeypatch):
    attempts = []
    def connect(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('Connection refused')
        return 'adb', 'frame:5555'
    monkeypatch.setattr(xr, 'open_adb', connect)
    monkeypatch.setattr(xr.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(xr, 'run_adb', lambda *a, **k: '123')
    assert xr.wait_for_browser('frame', 'org.chromium.chrome')['browser_running']
    assert len(attempts) == 2


def test_unconfirmed_start_does_not_report_browser_success(monkeypatch):
    monkeypatch.setattr(xr, 'open_adb', lambda *a, **k: ('adb', 'frame:5555'))
    monkeypatch.setattr(xr, 'run_adb', lambda *a, **k: '')
    result = xr.wait_for_browser('frame', 'org.chromium.chrome', timeout=0.01)
    assert not result['browser_running']
    assert 'nicht als laufend bestätigt' in result['startup_warning']


@pytest.mark.parametrize('existing', [True, False])
def test_samples_open_in_checked_browser_without_overwriting_other_tabs(monkeypatch, existing):
    monkeypatch.setattr(xr, 'browser_debug', lambda *a: nullcontext((
        'http://127.0.0.1:5000', {'webSocketDebuggerUrl': 'ws://frame/devtools/browser'})))
    class WS:
        closed = False
        def close(self): self.closed = True
    ws = WS()
    monkeypatch.setattr(xr, 'open_cdp', lambda *a: ws)
    calls = []
    def call(ws, method, params=None):
        calls.append((method, params))
        if method == 'Target.getTargets':
            return {'targetInfos': [
                {'targetId': 'unrelated', 'type': 'page', 'url': 'https://example.org'},
                *([{'targetId': 'sample', 'type': 'page', 'url': xr.SAMPLES}] if existing else [])]}
        return {'targetId': 'new-sample'} if method == 'Target.createTarget' else {}
    monkeypatch.setattr(xr, 'cdp_call', call)
    assert xr.open_samples('frame', 'org.chromium.chrome')['method'] == 'CDP'
    assert calls[-1] == ('Target.activateTarget', {'targetId': 'sample' if existing else 'new-sample'})
    assert ('Target.createTarget', {'url': xr.SAMPLES}) in calls if not existing else len(calls) == 2
    assert ws.closed


def test_cdp_uses_only_the_local_forwarding_endpoint(monkeypatch):
    import websocket
    calls = []
    monkeypatch.setattr(websocket, 'create_connection', lambda *a, **k: calls.append((a, k)))
    xr.open_cdp('ws://untrusted:9000/devtools/page/2', 'http://127.0.0.1:5000')
    assert calls[0][0] == ('ws://127.0.0.1:5000/devtools/page/2',)


def test_wrong_browser_package_is_rejected_and_forward_removed(monkeypatch):
    monkeypatch.setattr(xr, 'open_adb', lambda *a: ('adb', 'frame:5555'))
    calls = []
    def adb(*args, **kwargs):
        calls.append(args)
        if 'pidof' in args: return '123'
        if '/proc/net/unix' in args: return '0 @chrome_devtools_remote'
        return '5000'
    monkeypatch.setattr(xr, 'run_adb', adb)
    monkeypatch.setattr(xr.urllib.request, 'urlopen', lambda *a, **k:
                        io.BytesIO(b'{"Android-Package":"other.browser"}'))
    with pytest.raises(RuntimeError, match='nicht zum vorbereiteten'):
        xr.open_samples('frame', 'org.chromium.chrome')
    assert calls[-1][-3:] == ('forward', '--remove', 'tcp:5000')


def test_old_renderer_error_does_not_override_a_live_renderer(monkeypatch):
    ticks = iter((0, 10))
    monkeypatch.setattr(xr.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(xr, 'open_adb', lambda *a: ('adb', 'frame:5555'))
    def adb(*args, **kwargs):
        if 'pidof' in args: return '123'
        if 'ps' in args: return 'root 123 org.chromium.chrome:sandboxed_process0'
        if 'logcat' in args: return 'F m.chrome_zygot: setresgid(90000) failed: Invalid argument'
        return ''
    monkeypatch.setattr(xr, 'run_adb', adb)
    with pytest.raises(xr.ManualTestRequired, match='Debugschnittstelle'):
        xr.diagnose('frame', 'org.chromium.chrome')


def test_debug_socket_can_appear_after_the_browser_process(monkeypatch):
    monkeypatch.setattr(xr, 'open_adb', lambda *a: ('adb', 'frame:5555'))
    monkeypatch.setattr(xr.time, 'sleep', lambda *a: None)
    sockets = []
    calls = []
    def adb(*args, **kwargs):
        calls.append(args)
        if 'pidof' in args: return '123'
        if '/proc/net/unix' in args:
            sockets.append(1)
            return '0 @chrome_devtools_remote' if len(sockets) > 1 else ''
        return '5000'
    monkeypatch.setattr(xr, 'run_adb', adb)
    monkeypatch.setattr(xr.urllib.request, 'urlopen', lambda *a, **k:
                        io.BytesIO(b'{"Android-Package":"org.chromium.chrome"}'))
    with xr.browser_debug('frame', 'org.chromium.chrome') as (base, version):
        assert base == 'http://127.0.0.1:5000'
    assert len(sockets) == 2
    assert calls[-1][-3:] == ('forward', '--remove', 'tcp:5000')


def sample_diagnosis_mocks(monkeypatch, responses):
    monkeypatch.setattr(xr, 'browser_debug', lambda *a: nullcontext((
        'http://127.0.0.1:5000', {'Browser': 'Chrome/157'})))
    page = {'type': 'page', 'url': xr.SAMPLES,
            'webSocketDebuggerUrl': 'ws://frame/devtools/page/1'}
    unrelated = {'type': 'page', 'url': 'https://immersive-web.github.io/webxr-samples/tests/cube-sea.html',
                 'webSocketDebuggerUrl': 'ws://frame/devtools/page/9'}
    monkeypatch.setattr(xr.urllib.request, 'urlopen', lambda *a, **k:
                        io.BytesIO(json.dumps([unrelated, page]).encode()))
    class WS:
        closed = False
        def close(self): self.closed = True
    ws = WS()
    def open_checked(url, base):
        assert url == page['webSocketDebuggerUrl']
        return ws
    monkeypatch.setattr(xr, 'open_cdp', open_checked)
    iterator = iter(responses)
    monkeypatch.setattr(xr, 'cdp_call', lambda *a, **k: {'result': {'value': next(iterator)}})
    monkeypatch.setattr(xr.time, 'sleep', lambda *a: None)
    return ws


def test_diagnosis_waits_for_the_actual_sample_document(monkeypatch):
    initial = {'page_loaded': True, 'url': 'about:blank', 'secure': False, 'immersive_vr': False}
    loaded = {'page_loaded': True, 'url': xr.SAMPLES, 'secure': True, 'immersive_vr': True}
    ws = sample_diagnosis_mocks(monkeypatch, [initial, loaded])
    result = xr.diagnose('frame', 'org.chromium.chrome')
    assert result['immersive_vr'] and result['secure']
    assert result['url'] == xr.SAMPLES
    assert result['vr_verified'] is False and ws.closed


def test_blank_document_does_not_report_unsupported_xr(monkeypatch):
    ws = sample_diagnosis_mocks(monkeypatch, [
        {'page_loaded': True, 'url': 'about:blank', 'immersive_vr': False}])
    ticks = iter((0, 20))
    monkeypatch.setattr(xr.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(xr.ManualTestRequired, match='nicht vollständig geladen'):
        xr.diagnose('frame', 'org.chromium.chrome')
    assert ws.closed


def test_secure_user_selected_pages_are_allowed_but_local_files_are_rejected():
    assert xr.validate_test_page('https://example.org') == 'https://example.org/'
    with pytest.raises(ValueError, match='WebXR-Zieladresse'):
        xr.diagnose('frame', 'org.chromium.chrome', 'file:///data/local/private')


@pytest.mark.parametrize('url, landed, contexts', [
    ('https://xr-demo.example/vr', 'https://xr-demo.example/vr', [{'xrCompatible': True}]),
    ('https://xr-demo.example/vr', 'https://xr-demo.example/vr', [{'xrCompatible': False}]),
    ('https://example.org/vr', 'https://example.org/vr', [{'xrCompatible': True}]),
    ('https://example.org/vr', 'https://other.example.org/game/', [])])
def test_selected_page_prepares_before_navigation_and_preserves_other_tabs(monkeypatch, url, landed, contexts):
    monkeypatch.setattr(xr, 'browser_debug', lambda *a: nullcontext((
        'http://127.0.0.1:5000', {'Browser': 'Chrome/154',
                               'webSocketDebuggerUrl': 'ws://frame/devtools/browser/1'})))
    class WS:
        def __init__(self): self.closed = False
        def close(self): self.closed = True
    sockets = []
    def open_ws(url, base):
        sockets.append(WS())
        return sockets[-1]
    monkeypatch.setattr(xr, 'open_cdp', open_ws)
    # An unrelated page precedes the newly created one; only its ID is selected.
    pages = [{'id': 'other', 'type': 'page', 'webSocketDebuggerUrl': 'ws://frame/devtools/page/other'},
             {'id': 'prepared-page', 'type': 'page', 'webSocketDebuggerUrl': 'ws://frame/devtools/page/prepared-page'}]
    monkeypatch.setattr(xr.urllib.request, 'urlopen', lambda *a, **k:
                        io.BytesIO(json.dumps(pages).encode()))
    calls = []
    def call(ws, method, params=None):
        calls.append((method, params))
        if method == 'Target.getTargets':
            return {'targetInfos': [
                {'type': 'page', 'targetId': 'other', 'url': 'https://example.org'},
                {'type': 'page', 'targetId': 'old-page', 'url': url}]}
        if method == 'Target.closeTarget': return {'success': True}
        if method == 'Target.createTarget': return {'targetId': 'prepared-page'}
        if method == 'Page.addScriptToEvaluateOnNewDocument': return {'identifier': 'shim'}
        if method == 'Runtime.evaluate':
            return {'result': {'value': {'url': landed,
                'preparation': {'contexts': contexts}}}}
        return {}
    monkeypatch.setattr(xr, 'cdp_call', call)
    if all(context['xrCompatible'] for context in contexts):
        result = xr.open_prepared_page('frame', 'com.android.chrome', url)
        assert result['graphics_prepared'] is bool(contexts) and result['vr_verified'] is False
        assert result['url'] == landed and result['requested_url'] == url
        assert result['preparation_installed']
    else:
        with pytest.raises(RuntimeError, match='Grafik konnte nicht'):
            xr.open_prepared_page('frame', 'com.android.chrome', url)
    methods = [method for method, _ in calls]
    assert methods.index('Page.addScriptToEvaluateOnNewDocument') < methods.index('Page.navigate')
    assert ('Target.createTarget', {'url': 'about:blank'}) in calls
    assert calls[1] == ('Target.closeTarget', {'targetId': 'old-page'})
    assert ('Target.activateTarget', {'targetId': 'prepared-page'}) in calls
    assert ('Target.closeTarget', {'targetId': 'other'}) not in calls
    assert all(ws.closed for ws in sockets)


@pytest.mark.skipif(not shutil.which('node'), reason='Node für JavaScript-Regressionstest fehlt')
def test_generic_shim_prevents_legacy_xr_race_and_preserves_other_contexts():
    source = (xr.ROOT / 'assets/frame-webxr.js').read_text()
    regression = r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = JSON.parse(process.argv[1]);
function environment(origin, secure = true) {
    class Canvas {
        getContext(type, attributes) {
            if (type === '2d') return {type, attributes};
            let compatible = attributes?.xrCompatible === true;
            const alpha = attributes?.alpha;
            return {getContextAttributes: () => ({xrCompatible: compatible, alpha}),
                makeXRCompatible: () => Promise.resolve().then(() => {compatible = true})};
        }
    }
    const context = vm.createContext({window: {}, isSecureContext: secure,
        location: {origin, protocol: new URL(origin).protocol},
        HTMLCanvasElement: Canvas});
    return {Canvas, context};
}
// Reproduce the unawaited r117 call: the layer is constructed before the
// makeXRCompatible promise has updated the context's compatibility.
function oldManager(gl) {
    if (!gl.getContextAttributes().xrCompatible) gl.makeXRCompatible();
    if (!gl.getContextAttributes().xrCompatible) throw new Error('InvalidStateError');
}
const {Canvas, context} = environment('https://xr-demo.example');
assert.throws(() => oldManager(new Canvas().getContext('webgl', {})), /InvalidStateError/);
vm.runInContext(source, context);
const attributes = {antialias: true, xrCompatible: false};
const gl = new Canvas().getContext('webgl', attributes);
assert.doesNotThrow(() => oldManager(gl));
assert.equal(attributes.xrCompatible, false); // caller's options are untouched
assert.equal(new Canvas().getContext('2d', attributes).attributes, attributes);
const inherited = Object.freeze(Object.create({alpha: false, xrCompatible: false}));
assert.equal(new Canvas().getContext('webgl', inherited).getContextAttributes().alpha, false);
const getters = {get alpha() {assert.equal(this, getters); return false;},
    get unusedOption() {throw new Error('an unknown option must not be read');}};
assert.equal(new Canvas().getContext('webgl', getters).getContextAttributes().alpha, false);
assert.equal(context.window.__frameWebXR.contexts[0].xrCompatible, true);
const patched = Canvas.prototype.getContext;
vm.runInContext(source, context);
assert.equal(Canvas.prototype.getContext, patched); // no nested wrappers
for (let i=0; i<100; ++i) new Canvas().getContext('webgl2');
assert.equal(context.window.__frameWebXR.contexts.length, 32); // bounded bookkeeping
const other = environment('https://example.org');
const original = other.Canvas.prototype.getContext;
vm.runInContext(source, other.context);
assert.notEqual(other.Canvas.prototype.getContext, original);
assert.doesNotThrow(() => oldManager(new other.Canvas().getContext('webgl')));
for (const [origin, secure] of [['http://example.org', false], ['chrome://flags', true]]) {
    const ignored = environment(origin, secure);
    const original = ignored.Canvas.prototype.getContext;
    vm.runInContext(source, ignored.context);
    assert.equal(ignored.Canvas.prototype.getContext, original);
    assert.equal(ignored.context.window.__frameWebXR, undefined);
}
'''
    result = subprocess.run([shutil.which('node'), '-e', regression, json.dumps(source)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
