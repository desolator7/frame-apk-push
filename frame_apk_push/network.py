"""Use a directly attached LAN when a VPN overlaps the headset subnet."""
import ipaddress
import json
import os
from pathlib import Path
import select
import socket
import socketserver
import subprocess
import sys
import threading
from contextlib import contextmanager


def local_interface(host):
    try:
        address = ipaddress.ip_address(socket.gethostbyname(host))
        devices = json.loads(subprocess.check_output(['ip', '-j', 'address', 'show'], text=True, timeout=3))
        route = json.loads(subprocess.check_output(['ip', '-j', 'route', 'get', str(address)], text=True, timeout=3))[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    candidates = []
    for device in devices:
        name = device['ifname']
        if 'UP' not in device.get('flags', []) or not (Path('/sys/class/net') / name / 'device').exists():
            continue
        for info in device.get('addr_info', []):
            if info.get('family') == 'inet':
                network = ipaddress.ip_interface(f"{info['local']}/{info['prefixlen']}").network
                if address in network:
                    candidates.append((network.prefixlen, name))
    if not candidates:
        return None
    name = max(candidates)[1]
    return name if route.get('dev') != name else None


def bound_socket(host, port, interface, timeout=15):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b'\0')
        sock.settimeout(timeout)
        sock.connect((host, int(port)))
        return sock
    except BaseException:
        sock.close()
        raise


@contextmanager
def lan_tcp_forward(host, port, interface, timeout=5):
    """Keep one loopback-only relay on the selected LAN for this operation."""
    stopped = threading.Event()
    lock = threading.Lock()
    connections = set()

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            remote = None
            with lock:
                connections.add(self.request)
            try:
                remote = bound_socket(host, port, interface, timeout=timeout)
                with lock:
                    connections.add(remote)
                self.request.settimeout(2)
                remote.settimeout(2)
                while not stopped.is_set():
                    ready, _, _ = select.select([self.request, remote], [], [], 0.2)
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        destination = remote if source is self.request else self.request
                        destination.sendall(data)
            except (OSError, ValueError):
                # A failed LAN connection appears as a closed TCP connection to
                # ADB, which supplies the user-facing error with the operation.
                pass
            finally:
                with lock:
                    connections.discard(self.request)
                    connections.discard(remote)
                if remote:
                    remote.close()

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        block_on_close = False

    server = Server(('127.0.0.1', 0), Relay)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={'poll_interval': 0.1}, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        stopped.set()
        server.shutdown()
        with lock:
            active = list(connections)
        for connection in active:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        server.server_close()
        thread.join(timeout=2)


def configure_valve(host, valve):
    import paramiko
    interface = local_interface(host)
    if not interface:
        return None
    original = paramiko.SSHClient.connect
    def connect(client, hostname, *args, **kwargs):
        if kwargs.get('sock') is None:
            kwargs['sock'] = bound_socket(hostname, kwargs.get('port', 22), interface)
            try:
                return original(client, hostname, *args, **kwargs)
            except BaseException:
                kwargs['sock'].close()
                raise
        return original(client, hostname, *args, **kwargs)
    paramiko.SSHClient.connect = connect
    os.environ['FRAME_APK_PUSH_INTERFACE'] = interface
    os.environ['FRAME_APK_PUSH_PYTHON'] = sys.executable
    _, _, rsync, known_hosts = valve.locate_cygwin_tools()
    wrapper = Path(__file__).resolve().parents[1] / 'tools/frame-ssh'
    valve.g_external_tools = (None, str(wrapper), rsync, known_hosts)
    return interface
