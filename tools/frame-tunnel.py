"""Raw SSH byte relay. Used only by OpenSSH ProxyCommand, with no credentials."""
import os
from pathlib import Path
import select
import socket
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frame_apk_push.network import bound_socket
sock = bound_socket(sys.argv[2], sys.argv[3], sys.argv[1])
sock.settimeout(None)
stdin_open = True
try:
    while True:
        ready, _, _ = select.select([sock, 0] if stdin_open else [sock], [], [])
        if sock in ready:
            data = sock.recv(65536)
            if not data:
                break
            while data:
                data = data[os.write(1, data):]
        if 0 in ready:
            data = os.read(0, 65536)
            if data:
                sock.sendall(data)
            else:
                stdin_open = False
                sock.shutdown(socket.SHUT_WR)
finally:
    sock.close()
