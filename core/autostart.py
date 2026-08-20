# -*- coding: utf-8 -*-
"""
core/autostart.py
Lop Supervisor: theo doi lien tuc (thread nen) de dam bao:
  - Bridge luon chay (tu khoi dong lai neu tat).
  - Du proxy duoc dat cho tung emulator dang chay (tu set lai neu bi mat).
Phat tín hieu (callback) moi vong de GUI cap nhat nhanh.
"""
import time
import threading


class Supervisor:
    def __init__(self, bridge_mgr, emu_mgr, proxy_mgr, default_proxy,
                 interval=10, callback=None, enabled=True, pool=None,
                 default_socks_port=8080):
        self.bridge = bridge_mgr
        self.emu = emu_mgr
        self.proxy = proxy_mgr
        self.default_proxy = default_proxy
        self.pool = pool                     # BridgePool (co the None)
        self.default_socks_port = default_socks_port
        self.interval = interval
        self.callback = callback          # callback(dict_report)
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread = None

    # ---------- điều khiển ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def set_interval(self, sec):
        self.interval = sec

    # ---------- vòng lặp ----------
    def _loop(self):
        while not self._stop.is_set():
            try:
                if self.enabled:
                    report = self.supervise_once()
                    if self.callback:
                        self.callback(report)
            except Exception:
                pass
            # cho den interval hoac bi stop
            self._stop.wait(self.interval)

    # ---------- một vòng giám sát ----------
    def supervise_once(self):
        """Kiem tra bridge + proxy cua moi emulator dang chay. Tra ve dict."""
        report = {
            "timestamp": time.strftime("%H:%M:%S"),
            "bridge_running": self.bridge._port_listening(),
            "emulators": {},
            "actions": [],
        }

        # 1) Dam bao bridge chay
        if not report["bridge_running"]:
            ok, msg = self.bridge.start()
            report["actions"].append(("bridge", msg))
            report["bridge_running"] = self.bridge._port_listening()

        # 2) Dam bao proxy cho tung emulator dang chay
        try:
            status = self.emu.avd_status()
        except Exception:
            status = {}
        for avd, info in status.items():
            entry = {
                "avd": avd,
                "running": info["running"],
                "booted": info["booted"],
                "proxy": None,
                "ok": False,
            }
            # Xac dinh proxy mong doi cho AVD nay
            expected = self.default_proxy
            if self.pool is not None:
                p = self.pool.proxy_for_avd(avd)
                if p:
                    expected = p
            if info["running"] and info["booted"]:
                serial = info["serial"]
                try:
                    cur = self.proxy.get_proxy(serial)
                    entry["proxy"] = cur
                    if cur != expected and cur not in ("null", ""):
                        # set lai
                        self.proxy.set_proxy(serial, expected)
                        cur = self.proxy.get_proxy(serial)
                        report["actions"].append(("proxy", f"{avd}: reset -> {cur}"))
                    entry["proxy"] = cur
                    entry["ok"] = (cur == expected)
                except Exception as e:
                    entry["proxy"] = f"ERR {e}"
            elif info["running"]:
                entry["proxy"] = "dang boot..."
            report["emulators"][avd] = entry
        return report
