# -*- coding: utf-8 -*-
"""
core/proxy.py
Lop quan ly proxy cho tung Android emulator: doc proxy hien tai, dat/gỡ proxy,
kiem tra proxy hoat dong (tai IP cong cong qua proxy).
"""
import os
import subprocess
import time
from .emulator import EmulatorManager


def _hostname_of(url):
    """Tach hostname (bo scheme http/https va path) tu URL."""
    h = url
    for pre in ("http://", "https://"):
        if h.startswith(pre):
            h = h[len(pre):]
            break
    if "/" in h:
        h = h.split("/", 1)[0]
    if ":" in h and not h.startswith("["):
        h = h.split(":", 1)[0]
    return h



class ProxyManager:
    def __init__(self, sdk_path, default_proxy="10.0.2.2:8080"):
        self.emu = EmulatorManager(sdk_path)
        self.default_proxy = default_proxy

    # ---------- helpers ----------
    def _adb(self, serial, *args):
        cmd = [self.emu.adb, "-s", serial, *args]
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = 0x08000000
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                               creationflags=creationflags)
            return (p.stdout or "").strip()
        except Exception as e:
            return f"ERROR: {e}"

    # ---------- đọc/ghi proxy ----------
    def get_proxy(self, serial):
        """Tra ve chuoi http_proxy hien tai cua device (vd '10.0.2.2:8080' hoac 'null')."""
        return self._adb(serial, "shell", "settings", "get", "global", "http_proxy")

    def set_proxy(self, serial, proxy_str):
        """Dat proxy toan he thong. Tra ve True/False."""
        self._adb(serial, "shell", "settings", "put", "global", "http_proxy", proxy_str)
        return True

    def remove_proxy(self, serial):
        """Go proxy (dung :0). Tra ve True/False."""
        self._adb(serial, "shell", "settings", "put", "global", "http_proxy", ":0")
        return True

    def ensure_proxy(self, serial, proxy_str=None):
        """Dam bao proxy duoc dat; neu chua dung thi set lai."""
        proxy_str = proxy_str or self.default_proxy
        cur = self.get_proxy(serial)
        # 'null' cung coi la chua dat
        if cur != proxy_str or cur == "null" or cur == "":
            self.set_proxy(serial, proxy_str)
        return self.get_proxy(serial)

    # ---------- kiểm tra ----------
    def _http_get_via_port(self, port, host="http://api.ipify.org", timeout=15):
        """Gui GET qua bridge tren port cho truoc (chay tren HOST, 127.0.0.1).
        Tra ve (True, <IP>) hoac (False, <ly do>)."""
        req = (
            f"GET {host}/ HTTP/1.1\r\n"
            f"Host: {_hostname_of(host)}\r\n"
            "Connection: close\r\n\r\n"
        )
        try:
            import socket
            s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
            s.sendall(req.encode())
            data = b""
            s.settimeout(timeout)
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\r\n\r\n" in data and b"</" in data:
                    break
            s.close()
            header = data.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1", "replace")
            lines = header.split("\r\n")
            status = lines[0] if lines else "?"
            if "200" in status:
                body = data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b""
                ip = body.decode("iso-8859-1", "replace").strip().splitlines()
                ip_str = ip[-1] if ip else "?"
                return (True, f"{ip_str}")
            return (False, f"HTTP khong 200: {status}")
        except Exception as e:
            return (False, f"{e}")

    def test_proxy(self, serial, host="http://api.ipify.org", timeout=15):
        """Kiem tra proxy cua device qua port dang duoc dat trong http_proxy."""
        cur = self.get_proxy(serial)
        if cur in ("null", "", None):
            return (False, "proxy chua duoc dat (null)")
        _, _, port_part = cur.partition(":")
        port = int(port_part) if port_part.isdigit() else 8080
        ok, res = self._http_get_via_port(port, host, timeout)
        return (ok, res)

    def test_proxy_port(self, serial, port, host="http://api.ipify.org", timeout=15):
        """Kiem tra proxy qua mot port bridge cu the (dung cho pool)."""
        ok, res = self._http_get_via_port(port, host, timeout)
        return (ok, res)


