from __future__ import annotations

import threading
import time
from typing import Callable

from .bridge import BridgeRegistry
from .emulator import EmulatorManager
from .proxy import ProxyManager
from .state import StateStore


class Supervisor:
    def __init__(
        self,
        registry: BridgeRegistry,
        emulators: EmulatorManager,
        proxy: ProxyManager,
        state: StateStore,
        interval: int = 10,
        callback: Callable[[dict], None] | None = None,
        enabled: bool = True,
    ):
        self.registry = registry
        self.emulators = emulators
        self.proxy = proxy
        self.state = state
        self.interval = max(1, int(interval))
        self.callback = callback
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="proxy-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)

    def set_interval(self, seconds: int) -> None:
        self.interval = max(1, int(seconds))

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.enabled:
                try:
                    report = self.supervise_once()
                    if self.callback:
                        self.callback(report)
                except Exception as exc:
                    if self.callback:
                        self.callback({"timestamp": time.strftime("%H:%M:%S"), "error": str(exc), "actions": []})
            self._stop.wait(self.interval)

    def supervise_once(self) -> dict:
        report = {
            "timestamp": time.strftime("%H:%M:%S"),
            "bridges": {},
            "emulators": {},
            "actions": [],
        }
        report["actions"].extend(self.registry.ensure_all())
        report["bridges"] = self.registry.health()

        try:
            status = self.emulators.avd_status()
        except Exception as exc:
            report["actions"].append(("emulator_error", str(exc)))
            status = {}

        assignments = self.state.all_assignments()
        for avd, assignment in assignments.items():
            info = status.get(avd, {"running": False, "booted": False, "serial": None})
            entry = {
                "running": bool(info.get("running")),
                "booted": bool(info.get("booted")),
                "serial": info.get("serial"),
                "expected_proxy": self.registry.proxy_for_avd(avd),
                "proxy": None,
                "ok": False,
            }
            if entry["running"] and entry["booted"] and entry["serial"]:
                current = self.proxy.get_proxy(entry["serial"])
                entry["proxy"] = current.proxy
                if not current.success:
                    report["actions"].append(("proxy_error", f"{avd}: {current.error}"))
                elif current.proxy != entry["expected_proxy"]:
                    restored = self.proxy.set_proxy(entry["serial"], entry["expected_proxy"])
                    entry["proxy"] = restored.proxy
                    entry["ok"] = restored.success
                    if restored.success:
                        report["actions"].append(("proxy", f"{avd}: restored {restored.proxy}"))
                    else:
                        report["actions"].append(("proxy_error", f"{avd}: {restored.error}"))
                else:
                    entry["ok"] = True
            elif entry["running"]:
                entry["proxy"] = "booting"
            report["emulators"][avd] = entry
        return report
