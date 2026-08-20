from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .models import Assignment, SocksProxy


class _AtomicJsonStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read(self, default: dict) -> dict:
        with self._lock:
            if not self.path.exists():
                return default.copy()
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError(f"{self.path} must contain a JSON object")
            return data

    def _write(self, data: dict, private: bool = False) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent, text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                os.replace(temp_name, self.path)
                if private:
                    try:
                        os.chmod(self.path, 0o600)
                    except OSError:
                        pass
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)


class StateStore(_AtomicJsonStore):
    def all_assignments(self) -> dict[str, Assignment]:
        raw = self._read({"version": 1, "assignments": {}}).get("assignments", {})
        result: dict[str, Assignment] = {}
        for avd, item in raw.items():
            try:
                result[avd] = Assignment(avd, str(item["proxy_id"]), int(item["local_port"]))
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def get(self, avd: str) -> Assignment | None:
        return self.all_assignments().get(avd)

    def set(self, assignment: Assignment) -> None:
        data = self._read({"version": 1, "assignments": {}})
        data.setdefault("version", 1)
        data.setdefault("assignments", {})[assignment.avd] = assignment.as_dict()
        self._write(data)

    def remove(self, avd: str) -> Assignment | None:
        current = self.get(avd)
        data = self._read({"version": 1, "assignments": {}})
        data.setdefault("assignments", {}).pop(avd, None)
        self._write(data)
        return current

    def update_port_for_proxy(self, proxy_id: str, port: int) -> None:
        data = self._read({"version": 1, "assignments": {}})
        changed = False
        for item in data.setdefault("assignments", {}).values():
            if item.get("proxy_id") == proxy_id:
                item["local_port"] = int(port)
                changed = True
        if changed:
            self._write(data)


class ProxyStore(_AtomicJsonStore):
    def all(self) -> dict[str, SocksProxy]:
        raw = self._read({"version": 1, "proxies": {}}).get("proxies", {})
        result: dict[str, SocksProxy] = {}
        for proxy_id, item in raw.items():
            try:
                result[proxy_id] = SocksProxy(
                    host=str(item["host"]),
                    port=int(item["port"]),
                    username=str(item.get("username", "")),
                    password=str(item.get("password", "")),
                )
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def get(self, proxy_id: str) -> SocksProxy | None:
        return self.all().get(proxy_id)

    def upsert(self, proxy: SocksProxy) -> str:
        data = self._read({"version": 1, "proxies": {}})
        data.setdefault("version", 1)
        data.setdefault("proxies", {})[proxy.proxy_id] = proxy.as_secret_dict()
        self._write(data, private=True)
        return proxy.proxy_id

    def remove(self, proxy_id: str) -> None:
        data = self._read({"version": 1, "proxies": {}})
        data.setdefault("proxies", {}).pop(proxy_id, None)
        self._write(data, private=True)
