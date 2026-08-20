from __future__ import annotations

import socket
from urllib.parse import urlsplit

from .emulator import EmulatorManager
from .models import CommandResult, ProxyResult


class ProxyManager:
    def __init__(self, emulator_manager: EmulatorManager):
        self.emu = emulator_manager

    def _adb(self, serial: str, *args: str) -> CommandResult:
        return self.emu._run([self.emu.adb, "-s", serial, *args], timeout=30)

    def get_proxy(self, serial: str) -> ProxyResult:
        result = self._adb(serial, "shell", "settings", "get", "global", "http_proxy")
        if not result.success:
            return ProxyResult(False, error=result.error)
        return ProxyResult(True, proxy=result.stdout.strip())

    def set_proxy(self, serial: str, proxy_str: str) -> ProxyResult:
        result = self._adb(
            serial, "shell", "settings", "put", "global", "http_proxy", proxy_str
        )
        if not result.success:
            return ProxyResult(False, error=result.error)
        verify = self.get_proxy(serial)
        if not verify.success:
            return verify
        if verify.proxy != proxy_str:
            return ProxyResult(
                False,
                proxy=verify.proxy,
                error=f"proxy verification failed: expected {proxy_str}, got {verify.proxy}",
            )
        return ProxyResult(True, proxy=verify.proxy)

    def remove_proxy(self, serial: str) -> ProxyResult:
        result = self._adb(serial, "shell", "settings", "put", "global", "http_proxy", ":0")
        if not result.success:
            return ProxyResult(False, error=result.error)
        verify = self.get_proxy(serial)
        if not verify.success:
            return verify
        cleared = verify.proxy in {":0", "null", "", None}
        return ProxyResult(cleared, proxy=verify.proxy, error=None if cleared else "proxy was not cleared")

    def ensure_proxy(self, serial: str, expected: str) -> ProxyResult:
        current = self.get_proxy(serial)
        if not current.success:
            return current
        if current.proxy == expected:
            return current
        return self.set_proxy(serial, expected)

    @staticmethod
    def _http_get_via_port(port: int, url: str, timeout: int = 15) -> tuple[bool, str]:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname:
            return False, "proxy test URL must currently be plain http://"
        target = parsed.geturl()
        host_header = parsed.hostname
        if parsed.port:
            host_header += f":{parsed.port}"
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii", "strict")
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(request)
                data = bytearray()
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        return False, "response exceeded 1 MiB"
            head, _, body = bytes(data).partition(b"\r\n\r\n")
            status = head.split(b"\r\n", 1)[0].decode("iso-8859-1", "replace")
            if " 200 " not in f" {status} ":
                return False, status or "invalid HTTP response"
            return True, body.decode("utf-8", "replace").strip()
        except Exception as exc:
            return False, str(exc)

    def test_proxy_port(self, port: int, url: str = "http://api.ipify.org", timeout: int = 15) -> tuple[bool, str]:
        return self._http_get_via_port(port, url, timeout)
