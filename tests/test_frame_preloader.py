"""Exercise the native preloader against a real WebSocket/CDP mock peer."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import threading

import pytest
from frame_apk_push.core import ROOT


@pytest.fixture(scope='module')
def java_peer(tmp_path_factory):
    jdk = os.environ.get('FRAME_APK_PUSH_TEST_JDK')
    javac = str(Path(jdk) / 'bin/javac') if jdk else shutil.which('javac')
    java = str(Path(jdk) / 'bin/java') if jdk else shutil.which('java')
    if not java or not javac:
        pytest.skip('JDK required for the native DevTools transport checks')
    work = tmp_path_factory.mktemp('preloader')
    source = work / 'FramePreloaderCheck.java'
    source.write_text('''
import java.net.Socket;
import java.io.EOFException;
import java.nio.file.Paths;
public final class FramePreloaderCheck {
    public static void main(String[] args) throws Exception {
        try (Socket socket = new Socket("127.0.0.1", Integer.parseInt(args[0]))) {
            socket.setSoTimeout(200);
            try (FrameDevtools client = new FrameDevtools(socket.getInputStream(), socket.getOutputStream())) {
                switch(args[1]) {
                case "receive": System.out.println(client.receive()); break;
                case "send": client.text(new String(new char[70000]).replace('\\0', 'a')); break;
                case "version": System.out.println(client.version()); break;
                case "upgrade":
                case "upgradeAndroid":
                    client.upgrade("ws://ignored/devtools/browser" + (args[1].equals("upgrade") ? "/test" : ""));
                    System.out.println(client.receive()); break;
                case "serve":
                    try { new FrameBrowserXR("com.android.chrome", "window.__frameWebXR = {}", Paths.get(args[2])).serve(client); }
                    catch (EOFException closed) { /* peer deliberately ended the test */ }
                    break;
                default: throw new IllegalArgumentException();
                }
            }
        }
    }
}''')
    subprocess.run([javac, '--release', '8', '-d', str(work),
                    str(ROOT / 'native/FrameDevtools.java'),
                    str(ROOT / 'native/FrameBrowserXR.java'), str(source)],
                   check=True, capture_output=True)
    classpath = str(work)
    if os.environ.get('FRAME_APK_PUSH_TEST_JSON'):
        classpath += os.pathsep + os.environ['FRAME_APK_PUSH_TEST_JSON']
    return java, classpath, work


def read_exact(peer, size):
    result = b''
    while len(result) < size:
        chunk = peer.recv(size - len(result))
        if not chunk:
            raise EOFError()
        result += chunk
    return result


def receive_client(peer):
    header = read_exact(peer, 2)
    assert header[0] & 128 and header[1] & 128, 'client frames must be final and masked'
    length = header[1] & 127
    if length == 126:
        length = struct.unpack('!H', read_exact(peer, 2))[0]
    elif length == 127:
        length = struct.unpack('!Q', read_exact(peer, 8))[0]
    mask = read_exact(peer, 4)
    payload = read_exact(peer, length)
    return header[0] & 15, bytes(value ^ mask[i % 4] for i, value in enumerate(payload))


def server_frame(value, opcode=1, final=True):
    payload = value.encode() if isinstance(value, str) else value
    header = bytes([(128 if final else 0) | opcode])
    if len(payload) < 126:
        header += bytes([len(payload)])
    elif len(payload) < 65536:
        header += b'\x7e' + struct.pack('!H', len(payload))
    else:
        header += b'\x7f' + struct.pack('!Q', len(payload))
    return header + payload


def exchange(java_peer, mode, handler):
    java, classpath, work = java_peer
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(10)
        errors = []
        def serve():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(8)
                    handler(peer)
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=serve)
        thread.start()
        result = subprocess.run([java, '-cp', classpath, 'FramePreloaderCheck',
            str(listener.getsockname()[1]), mode, str(work / 'status.json')],
            capture_output=True, text=True, timeout=12)
        thread.join(10)
        assert not thread.is_alive()
        if errors:
            raise errors[0]
        return result


def test_fragmented_message_handles_interleaved_ping_and_masks_pong(java_peer):
    def peer(sock):
        sock.sendall(server_frame('first ', final=False) + server_frame('ping', opcode=9) +
                     server_frame('second', opcode=0))
        assert receive_client(sock) == (10, b'ping')
    result = exchange(java_peer, 'receive', peer)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'first second'


def test_large_client_message_uses_64_bit_length_and_mask(java_peer):
    result = exchange(java_peer, 'send', lambda sock: (
        receive_client(sock) == (1, b'a' * 70000) or pytest.fail('incorrect payload')))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('data', [b'\x81\xff', b'\x80\x00', b'\x81\x7f' + struct.pack('!Q', 4194305)])
def test_invalid_or_oversized_server_frames_are_rejected(java_peer, data):
    result = exchange(java_peer, 'receive', lambda sock: sock.sendall(data))
    assert result.returncode != 0
    assert 'IOException' in result.stderr


def test_partial_frame_timeout_reconnects_instead_of_parsing_remaining_bytes(java_peer):
    def peer(sock):
        sock.sendall(b'\x81\x05a')
        # Wait until the Java process rejects this partial frame and disconnects.
        assert sock.recv(1) == b''
    result = exchange(java_peer, 'receive', peer)
    assert result.returncode != 0 and 'Incomplete WebSocket frame' in result.stderr


@pytest.mark.parametrize('android', [False, True])
def test_http_version_and_websocket_handshake(java_peer, android):
    def version(sock):
        request = sock.makefile('rb')
        assert request.readline() == b'GET /json/version HTTP/1.1\r\n'
        while request.readline() != b'\r\n': pass
        body = b'{"Android-Package":"com.android.chrome"}'
        sock.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
    result = exchange(java_peer, 'version', version)
    assert result.returncode == 0 and json.loads(result.stdout)['Android-Package'] == 'com.android.chrome'
    def upgrade(sock):
        request = sock.makefile('rb')
        assert request.readline() == b'GET /devtools/browser' + (b'' if android else b'/test') + b' HTTP/1.1\r\n'
        headers = {}
        while True:
            line = request.readline()
            if line == b'\r\n': break
            name, value = line.decode().strip().split(': ', 1)
            headers[name.lower()] = value
        accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] +
            '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        sock.sendall(b'HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: ' + accept +
                     b'\r\n\r\n' + server_frame('ready'))
    result = exchange(java_peer, 'upgradeAndroid' if android else 'upgrade', upgrade)
    assert result.returncode == 0 and result.stdout.strip() == 'ready'


@pytest.mark.parametrize('failure', [None, 'Page.enable', 'Page.addScriptToEvaluateOnNewDocument', 'Target.setAutoAttach'])
def test_document_preload_precedes_resume_and_errors_release_the_page(java_peer, failure):
    if not os.environ.get('FRAME_APK_PUSH_TEST_JSON'):
        pytest.skip('Set FRAME_APK_PUSH_TEST_JSON to a JSON-Java jar for protocol state checks')
    seen = {'tab': [], 'page': [], 'iframe': []}
    def peer(sock):
        def send(value): sock.sendall(server_frame(json.dumps(value)))
        _, payload = receive_client(sock)
        command = json.loads(payload)
        assert command['method'] == 'Target.setAutoAttach'
        assert command['params']['waitForDebuggerOnStart'] is True
        assert command['params']['filter'][0] == {'type': 'tab'}
        send({'id': command['id'], 'result': {}})
        for session in seen:
            send({'method': 'Target.attachedToTarget', 'params': {'sessionId': session,
                'waitingForDebugger': True, 'targetInfo': {'type': session}}})
        resumed = set()
        held = []
        while len(resumed) < len(seen):
            _, payload = receive_client(sock)
            command = json.loads(payload)
            session, method = command['sessionId'], command['method']
            seen[session].append(method)
            if method == 'Runtime.runIfWaitingForDebugger':
                resumed.add(session)
                if session == 'tab':
                    # Android cannot enable the page until its tab
                    # container is released. The page itself remains paused.
                    for reply in held: send(reply)
                    held.clear()
            if method == failure and session != 'tab':
                send({'id': command['id'], 'sessionId': session, 'error': {'code': -32000}})
            else:
                if method == 'Page.addScriptToEvaluateOnNewDocument':
                    assert command['params']['runImmediately'] is True
                reply = {'id': command['id'], 'sessionId': session,
                         'result': {'identifier': 'installed'} if method.startswith('Page.addScript') else {}}
                if method == 'Page.enable' and 'tab' not in resumed:
                    held.append(reply)
                else:
                    send(reply)
    result = exchange(java_peer, 'serve', peer)
    assert result.returncode == 0, result.stderr
    assert seen.pop('tab') == ['Target.setAutoAttach', 'Runtime.runIfWaitingForDebugger']
    for methods in seen.values():
        assert methods[0] == 'Page.addScriptToEvaluateOnNewDocument' and methods[-1] == 'Runtime.runIfWaitingForDebugger'
        if failure is None:
            assert methods == ['Page.addScriptToEvaluateOnNewDocument', 'Page.enable',
                               'Target.setAutoAttach', 'Runtime.runIfWaitingForDebugger']
        else:
            assert methods[-2] == failure
