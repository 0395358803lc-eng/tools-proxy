# -*- coding: utf-8 -*-
"""
core/bridge.py
Lop quan ly cau noi HTTP<->SOCKS5 (http2socks_bridge.py) tren HOST.
HoTro chay NHIEU bridge (moi bridge = 1 port + 1 proxy SOCKS5 rieng) de
moi emulator co the co mot dia chi IP thoat ra khac nhau.
"""
import os
import subprocess
import time


class BridgeManager:
    """Quan ly mot bridge don le (1 port, 1 SOCKS5)."""
    def __init__(self, bridge_script, bridge_port=8080, socks=None,
                 log_out=None, log_err=None):
        self.script = bridge_script
        self.port = bridge_port
        self.socks = socks          # dict host/port/user/password hoac None (dung default)
        self.workdir = os.path.dirname(bridge_script) if os.path.dirname(bridge_script) else "."
        # log file rieng cho moi bridge
        self.log_out = log_out or os.path.join(self.workdir, f"bridge_{bridge_port}_out.log")
        self.log_err = log_err or os.path.join(self.workdir, f"bridge_{bridge_port}_err.log")

    def _cmd(self):
        cmd = [self.script, str(self.port)]
        if self.socks:
            cmd += [self.socks["host"], str(self.socks["port"]),
                    self.socks["user"], self.socks["password"]]
        # Neu script la .py thi goi qua python; neu .exe thi goi truc tiep
        if str(self.script).lower().endswith(".py"):
            cmd.insert(0, "python")
        return cmd

    def _port_listening(self):
        """Kiem tra port co dang listen tren bat ky interface nao khong."""
        try:
            if os.name == "nt":
                out = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True,
                    timeout=20, creationflags=0x08000000,
                ).stdout
                marker = f":{self.port}"
                for line in out.splitlines():
                    if "LISTENING" in line and marker in line:
                        return True
                return False
            else:
                out = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=20).stdout
                return f":{self.port}" in out
        except Exception:
            return False

    def status(self):
        """Tra ve (bool running, str detail)."""
        socks_desc = ""
        if self.socks:
            socks_desc = f" -> SOCKS5 {self.socks['host']}:{self.socks['port']}"
        if self._port_listening():
            return (True, f"bridge port {self.port}{socks_desc} DANG CHAY")
        return (False, f"bridge port {self.port}{socks_desc} KHONG chay")

    def start(self):
        """Khoi dong bridge neu chua chay. Tra ve (bool, str)."""
        if self._port_listening():
            return (True, f"bridge da chay san (port {self.port})")
        try:
            if os.name == "nt":
                creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
            else:
                creationflags = 0
            p = subprocess.Popen(
                self._cmd(),
                cwd=self.workdir,
                stdout=open(self.log_out, "a"),
                stderr=open(self.log_err, "a"),
                creationflags=creationflags,
                close_fds=True,
            )
            for _ in range(10):
                time.sleep(0.5)
                if self._port_listening():
                    return (True, f"bridge port {self.port} da khoi dong (pid {p.pid})")
            return (False, f"bridge port {self.port} khoi dong nhung chua len")
        except Exception as e:
            return (False, f"ERROR khoi dong bridge: {e}")

    def stop(self):
        """Dung bridge dang chay. Tra ve str."""
        try:
            if os.name == "nt":
                out = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True,
                    timeout=20, creationflags=0x08000000,
                ).stdout
                marker = f":{self.port} "
                pids = set()
                for line in out.splitlines():
                    if marker in line and "LISTENING" in line:
                        parts = line.split()
                        if parts:
                            pids.add(parts[-1])
                for pid in pids:
                    subprocess.run(["taskkill", "/PID", pid, "/F"],
                                   capture_output=True, timeout=15,
                                   creationflags=0x08000000)
                return f"da go bridge port {self.port} (pid {', '.join(pids) if pids else 'khong tim thay'})"
            else:
                subprocess.run(["pkill", "-f", self.script], timeout=15)
                return f"da go bridge port {self.port}"
        except Exception as e:
            return f"ERROR stop bridge: {e}"

class BridgePool:
    """
    Quan ly NHIEU bridge (moi bridge 1 port + 1 SOCKS5) va gan cho moi emulator
    mot proxy rieng de co IP thoat ra khac nhau.
    """
    def __init__(self, bridge_script, port_base=8081):
        self.script = bridge_script
        self.port_base = port_base
        self.bridges = {}          # port -> BridgeManager
        self.assign = {}           # avd_name -> port (proxy dang gan)

    # ---------- phan tich ----------
    def socks_from_string(self, s):
        """Phan tich chuoi 'host:port:user:pass' -> dict. None neu loi."""
        s = s.strip()
        if not s:
            return None
        parts = s.split(":")
        if len(parts) < 4:
            return None
        try:
            port = int(parts[1])
        except ValueError:
            return None
        return {
            "host": parts[0],
            "port": port,
            "user": parts[2],
            "password": ":".join(parts[3:]),
        }

    def _is_port_used(self, port):
        try:
            if os.name == "nt":
                out = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True,
                    timeout=20, creationflags=0x08000000,
                ).stdout
                marker = f":{port} "
                for line in out.splitlines():
                    if "LISTENING" in line and marker in line:
                        return True
                return False
            return False
        except Exception:
            return False

    def _next_free_port(self):
        port = self.port_base
        while port in self.bridges or self._is_port_used(port):
            port += 1
        return port

    def allocate_bridge(self, socks_str):
        """
        Dam bao co mot bridge cho chuoi SOCKS5. Neu da co cung SOCKS5 => port cu.
        Neu chua co => tao bridge moi (port moi + SOCKS5). Tra ve port (hoac None).
        """
        socks = self.socks_from_string(socks_str)
        if not socks:
            return None
        for port, b in self.bridges.items():
            if b.socks and b.socks == socks:
                return port
        port = self._next_free_port()
        b = BridgeManager(self.script, port, socks=socks)
        ok, _ = b.start()
        if ok:
            self.bridges[port] = b
            return port
        return None

    def assign_proxy(self, avd_name, socks_str):
        """
        Gan proxy (chuoi 'host:port:user:pass') cho mot AVD.
        Tra ve (port, proxy_str '10.0.2.2:<port>') hoac (None, None) neu loi.
        """
        port = self.allocate_bridge(socks_str)
        if not port:
            return (None, None)
        self.assign[avd_name] = port
        return (port, f"10.0.2.2:{port}")

    def proxy_for_avd(self, avd_name):
        """Tra ve proxy_str '10.0.2.2:<port>' da gan cho AVD, hoac None."""
        port = self.assign.get(avd_name)
        if port:
            return f"10.0.2.2:{port}"
        return None

    def port_for_avd(self, avd_name):
        """Tra ve port cua proxy da gan cho AVD, hoac None."""
        return self.assign.get(avd_name)

    def socks_for_port(self, port):
        b = self.bridges.get(port)
        return b.socks if b else None

    def remove_avd(self, avd_name):
        """Bo gan proxy cho AVD (va dung bridge neu khong con AVD nao dung)."""
        port = self.assign.pop(avd_name, None)
        if not port:
            return (False, f"{avd_name} chua duoc gan proxy")
        # chi dung bridge neu khong con AVD nao khac dung port nay
        still_used = [a for a, p in self.assign.items() if p == port]
        msg = ""
        if not still_used:
            b = self.bridges.get(port)
            if b:
                msg = b.stop()
                self.bridges.pop(port, None)
        return (True, msg or f"da bo gan proxy cua {avd_name}")

