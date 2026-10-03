import json
import socket
from pathlib import Path
import pytest
from frame_apk_push import network


def test_vpn_overlap_prefers_direct_physical_lan(monkeypatch):
    devices = [{'ifname': 'wlan0', 'flags': ['UP'], 'addr_info': [
        {'family': 'inet', 'local': '203.0.113.25', 'prefixlen': 24}]}]
    def command(args, **kwargs):
        return json.dumps(devices if 'address' in args else [{'dev': 'wg_config'}])
    monkeypatch.setattr(network.subprocess, 'check_output', command)
    monkeypatch.setattr(network.socket, 'gethostbyname', lambda host: '203.0.113.55')
    monkeypatch.setattr(Path, 'exists', lambda path: str(path) == '/sys/class/net/wlan0/device')
    assert network.local_interface('frame') == 'wlan0'
    monkeypatch.setattr(network.subprocess, 'check_output', lambda args, **kwargs: json.dumps(devices if 'address' in args else [{'dev': 'wlan0'}]))
    assert network.local_interface('frame') is None


def test_bound_socket_is_closed_when_connect_fails(monkeypatch):
    import pytest
    class Socket:
        closed = False
        def setsockopt(self, *args): self.options = args
        def settimeout(self, timeout): pass
        def connect(self, address): raise TimeoutError()
        def close(self): self.closed = True
    sock = Socket()
    monkeypatch.setattr(network.socket, 'socket', lambda *args: sock)
    with pytest.raises(TimeoutError):
        network.bound_socket('203.0.113.55', 22, 'wlan0')
    assert sock.closed
    assert sock.options[-1] == b'wlan0\0'


def test_lan_relay_transfers_both_directions_and_closes_on_exit(monkeypatch):
    upstream, device = socket.socketpair()
    device.settimeout(2)
    calls = []
    def connect(host, port, interface, timeout):
        calls.append((host, port, interface))
        return upstream
    monkeypatch.setattr(network, 'bound_socket', connect)
    try:
        with network.lan_tcp_forward('frame', 5555, 'wlan0') as port:
            client = socket.create_connection(('127.0.0.1', port), timeout=2)
            try:
                client.sendall(b'ADB request')
                assert device.recv(100) == b'ADB request'
                device.sendall(b'Android response')
                assert client.recv(100) == b'Android response'
                assert calls == [('frame', 5555, 'wlan0')]
            except BaseException:
                client.close()
                raise
        assert client.recv(100) == b''
        client.close()
        assert device.recv(100) == b''
        with pytest.raises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=1)
    finally:
        upstream.close()
        device.close()


def test_lan_relay_reports_unreachable_frame_as_closed_connection(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError('Frame unreachable')
    monkeypatch.setattr(network, 'bound_socket', fail)
    with network.lan_tcp_forward('frame', 5555, 'wlan0') as port:
        with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
            assert client.recv(100) == b''
