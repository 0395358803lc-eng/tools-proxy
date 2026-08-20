from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .models import Assignment
from .state import ProxyStore, StateStore


class BridgeProcess:
    def __init__(
        self,
        script: str | Path,
        port: int,
        proxy_id: str,
        proxy_store_path: str | Path,
        bind_host: str = "127.0.0.1",
        log_dir: str | Path | None = None,
    ):
        self.script = Path(script)
        self.port = int(port)
        self.proxy_id = proxy_id
        self.proxy_store_path = Path(proxy_store_path)
        self.bind_host = bind_host
        self.log_dir = Path(log_dir or self.script.parent / "logs")
        self.process: subprocess.Popen | None = None

    def _command(self) -> list[str]:
        return [
            sys.executable,
            str(self.script),
            "--listen-host",
            self.bind_host,
            "--listen-port",
            str(self.port),
            "--proxy-file",
            str(self.proxy_store_path),
            "--proxy-id",
            self.proxy_id,
        ]

    def probe(self, timeout: float = 1.5) -> tuple[bool, dict | str]:
        request = (
            "GET http://proxy.local/__health__ HTTP/1.1\r\n"
            "Host: proxy.local\r\nConnection: close\r\n\r\n"
        ).encode("ascii")
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(request)
                data = bytearray()
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > 64 * 1024:
                        break
            head, _, body = bytes(data).partition(b"\r\n\r\n")
            if b" 200 " not in b" " + head.split(b"\r\n", 1)[0] + b" ":
                return False, "health endpoint did not return 200"
            payload = json.loads(body.decode("utf-8"))
            if payload.get("service") != "tools-proxy-bridge":
                return False, "port belongs to another service"
            if payload.get("proxy_id") != self.proxy_id:
                return False, "bridge proxy id mismatch"
            return True, payload
        except Exception as exc:
            return False, str(exc)

    def start(self, timeout: float = 6.0) -> tuple[bool, str]:
        ok, _ = self.probe()
        if ok:
            return True, f"bridge {self.port} already healthy"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.log_dir / f"bridge_{self.port}.log"
        err_path = self.log_dir / f"bridge_{self.port}.err.log"
        try:
            out_handle = open(out_path, "a", encoding="utf-8")
            err_handle = open(err_path, "a", encoding="utf-8")
            flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
            try:
                self.process = subprocess.Popen(
                    self._command(),
                    cwd=self.script.parent,
                    stdout=out_handle,
                    stderr=err_handle,
                    creationflags=flags,
                    close_fds=True,
                )
            finally:
                out_handle.close()
                err_handle.close()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ok, detail = self.probe()
                if ok:
                    return True, f"bridge {self.port} started pid={self.process.pid}"
                if self.process.poll() is not None:
                    return False, f"bridge exited with code {self.process.returncode}"
                time.sleep(0.25)
            return False, f"bridge {self.port} did not become healthy: {detail}"
        except Exception as exc:
            return False, f"failed to start bridge {self.port}: {exc}"

    def _listener_pids(self) -> set[int]:
        pids: set[int] = set()
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True, timeout=10,
                    creationflags=0x08000000,
                )
                marker = f":{self.port}"
                for line in result.stdout.splitlines():
                    if "LISTENING" not in line or marker not in line:
                        continue
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pids.add(int(parts[-1]))
            else:
                result = subprocess.run(
                    ["lsof", "-t", f"-iTCP:{self.port}", "-sTCP:LISTEN"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.splitlines():
                    if line.strip().isdigit():
                        pids.add(int(line.strip()))
        except Exception:
            pass
        return pids

    def stop(self) -> tuple[bool, str]:
        healthy, _ = self.probe()
        if not healthy and (self.process is None or self.process.poll() is not None):
            return True, f"bridge {self.port} already stopped"
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                return True, f"bridge {self.port} stopped"
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
                return True, f"bridge {self.port} killed"
            except Exception as exc:
                return False, str(exc)

        if healthy:
            pids = self._listener_pids()
            if not pids:
                return False, "healthy bridge found but listener PID could not be determined"
            try:
                for pid in pids:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(pid), "/F"],
                            capture_output=True, timeout=10, creationflags=0x08000000,
                        )
                    else:
                        os.kill(pid, signal.SIGTERM)
                return True, f"bridge {self.port} stopped (restored PID {','.join(map(str, sorted(pids)))})"
            except Exception as exc:
                return False, str(exc)
        return True, f"bridge {self.port} already stopped"


class BridgeRegistry:
    def __init__(
        self,
        script: str | Path,
        state: StateStore,
        proxies: ProxyStore,
        proxy_store_path: str | Path,
        port_base: int = 8081,
        bind_host: str = "127.0.0.1",
        emulator_gateway: str = "10.0.2.2",
        log_dir: str | Path | None = None,
    ):
        self.script = Path(script)
        self.state = state
        self.proxies = proxies
        self.proxy_store_path = Path(proxy_store_path)
        self.port_base = int(port_base)
        self.bind_host = bind_host
        self.emulator_gateway = emulator_gateway
        self.log_dir = Path(log_dir or self.script.parent / "logs")
        self._processes: dict[int, BridgeProcess] = {}
        self._lock = threading.RLock()

    def _bridge(self, port: int, proxy_id: str) -> BridgeProcess:
        current = self._processes.get(port)
        if current and current.proxy_id == proxy_id:
            return current
        bridge = BridgeProcess(
            self.script,
            port,
            proxy_id,
            self.proxy_store_path,
            bind_host=self.bind_host,
            log_dir=self.log_dir,
        )
        self._processes[port] = bridge
        return bridge

    def _port_available(self, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

    def _next_free_port(self) -> int:
        assigned = {a.local_port for a in self.state.all_assignments().values()}
        port = self.port_base
        while port in assigned or not self._port_available(port):
            port += 1
        return port

    def _existing_assignment_for_proxy(self, proxy_id: str) -> Assignment | None:
        for assignment in self.state.all_assignments().values():
            if assignment.proxy_id == proxy_id:
                return assignment
        return None

    def assign(self, avd: str, proxy_id: str) -> tuple[bool, str, int | None]:
        with self._lock:
            if self.proxies.get(proxy_id) is None:
                return False, f"proxy {proxy_id} is missing from local proxy store", None
            old = self.state.get(avd)
            same_proxy = self._existing_assignment_for_proxy(proxy_id)
            port = same_proxy.local_port if same_proxy else self._next_free_port()
            bridge = self._bridge(port, proxy_id)
            ok, message = bridge.start()
            if not ok:
                if same_proxy is not None:
                    new_port = self._next_free_port()
                    bridge = self._bridge(new_port, proxy_id)
                    ok, message = bridge.start()
                    if ok:
                        self.state.update_port_for_proxy(proxy_id, new_port)
                        port = new_port
                if not ok:
                    return False, message, None
            self.state.set(Assignment(avd=avd, proxy_id=proxy_id, local_port=port))
            if old and old.proxy_id != proxy_id:
                self._stop_port_if_unused(old.local_port)
            return True, message, port

    def _stop_port_if_unused(self, port: int) -> None:
        if any(a.local_port == port for a in self.state.all_assignments().values()):
            return
        bridge = self._processes.pop(port, None)
        if bridge:
            bridge.stop()

    def remove(self, avd: str) -> tuple[bool, str]:
        with self._lock:
            old = self.state.remove(avd)
            if old is None:
                return False, f"{avd} has no proxy assignment"
            self._stop_port_if_unused(old.local_port)
            return True, f"removed proxy assignment for {avd}"

    def proxy_for_avd(self, avd: str) -> str | None:
        assignment = self.state.get(avd)
        if assignment is None:
            return None
        return f"{self.emulator_gateway}:{assignment.local_port}"

    def port_for_avd(self, avd: str) -> int | None:
        assignment = self.state.get(avd)
        return assignment.local_port if assignment else None

    def ensure_all(self) -> list[tuple[str, str]]:
        actions: list[tuple[str, str]] = []
        with self._lock:
            groups: dict[str, list[Assignment]] = {}
            for assignment in self.state.all_assignments().values():
                groups.setdefault(assignment.proxy_id, []).append(assignment)
            for proxy_id, assignments in groups.items():
                if self.proxies.get(proxy_id) is None:
                    actions.append(("bridge_error", f"{proxy_id}: missing local credentials"))
                    continue
                port = assignments[0].local_port
                bridge = self._bridge(port, proxy_id)
                ok, detail = bridge.probe()
                if ok:
                    continue
                ok, message = bridge.start()
                if not ok:
                    new_port = self._next_free_port()
                    if new_port != port:
                        replacement = self._bridge(new_port, proxy_id)
                        ok, message = replacement.start()
                        if ok:
                            self.state.update_port_for_proxy(proxy_id, new_port)
                            port = new_port
                actions.append(("bridge" if ok else "bridge_error", f"{proxy_id}@{port}: {message}"))
        return actions

    def health(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        seen: set[tuple[str, int]] = set()
        for assignment in self.state.all_assignments().values():
            key = (assignment.proxy_id, assignment.local_port)
            if key in seen:
                continue
            seen.add(key)
            bridge = self._bridge(assignment.local_port, assignment.proxy_id)
            ok, detail = bridge.probe()
            result[assignment.proxy_id] = {
                "port": assignment.local_port,
                "healthy": ok,
                "detail": detail,
            }
        return result
