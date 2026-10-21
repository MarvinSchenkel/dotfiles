"""Minimal stdlib MA websocket client: run commands and dump their results as JSON.

Usage: /usr/bin/python3 ma_ws.py <outdir> <command> [<command> ...]
Reads MA_URL and MA_TOKEN from the environment. Writes <outdir>/<command with / as _>.json.
"""
import base64
import json
import os
import socket
import struct
import sys
from urllib.parse import urlparse


def main():
    outdir, commands = sys.argv[1], sys.argv[2:]
    url = urlparse(os.environ["MA_URL"])
    sock = socket.create_connection((url.hostname, url.port or 80), timeout=60)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        (
            f"GET /ws HTTP/1.1\r\nHost: {url.hostname}:{url.port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(4096)
    head, rest = buf.split(b"\r\n\r\n", 1)
    if b" 101 " not in head.split(b"\r\n")[0]:
        sys.exit(f"upgrade failed: {head[:200]!r}")
    conn = _Conn(sock, rest)
    conn.recv_json()  # server info greeting
    conn.send_json({"command": "auth", "message_id": "auth", "args": {"token": os.environ["MA_TOKEN"]}})
    auth = conn.wait_for("auth")
    if "error_code" in auth:
        sys.exit(f"auth failed: {auth.get('details')}")
    for cmd in commands:
        conn.send_json({"command": cmd, "message_id": cmd, "args": {}})
        msg = conn.wait_for(cmd)
        path = os.path.join(outdir, cmd.replace("/", "_") + ".json")
        with open(path, "w") as f:
            json.dump(msg.get("result", msg), f, indent=1, default=str)
        print(cmd, "error" if "error_code" in msg else "ok", path)


class _Conn:
    def __init__(self, sock, buf):
        self.sock, self.buf = sock, buf

    def send_json(self, obj):
        data = json.dumps(obj).encode()
        n = len(data)
        hdr = bytes([0x81])
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def wait_for(self, message_id):
        """Return the next message with this message_id, joining partial results."""
        parts = []
        while True:
            msg = self.recv_json()
            if msg.get("message_id") != message_id:
                continue
            if msg.get("partial"):
                parts.extend(msg.get("result") or [])
                continue
            if parts:
                msg["result"] = parts + (msg.get("result") or [])
            return msg

    def recv_json(self):
        payload = b""
        while True:
            fin, opcode, data = self._frame()
            if opcode == 0x9:
                continue
            if opcode == 0x8:
                sys.exit("server closed connection")
            payload += data
            if fin:
                return json.loads(payload)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                sys.exit("connection lost")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self):
        b1, b2 = self._read(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read(8))[0]
        return b1 & 0x80, b1 & 0x0F, self._read(n)


if __name__ == "__main__":
    main()
