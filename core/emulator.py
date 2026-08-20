# -*- coding: utf-8 -*-
"""
core/emulator.py
Lop quan ly Android emulators (AVD): liet ke AVD, detect trang thai dang chay,
khoi dong AVD, lay serial tu ten AVD.
"""
import os
import subprocess
import time
import re


class EmulatorManager:
    def __init__(self, sdk_path):
        self.sdk = sdk_path
        self.adb = os.path.join(sdk_path, "platform-tools", "adb.exe")
        self.emulator = os.path.join(sdk_path, "emulator", "emulator.exe")

    # ---------- helpers ----------
    def _run(self, cmd):
        """Chay lenh, tra ve stdout string (khong bao loi)."""
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = 0x08000000  # CREATE_NO_WINDOW
            p = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                creationflags=creationflags,
            )
            return (p.stdout or "") + (p.stderr or "")
        except Exception as e:
            return f"ERROR: {e}"

    # ---------- liệt kê ----------
    def list_avds(self):
        """Tra ve danh sach ten cac AVD."""
        out = self._run([self.emulator, "-list-avds"])
        avds = [ln.strip() for ln in out.splitlines() if ln.strip()]
        return avds

    # ---------- trạng thái ----------
    def running_serials(self):
        """Tra ve danh sach serial dang 'device' (da ket noi)."""
        out = self._run([self.adb, "devices"])
        serials = []
        for line in out.splitlines():
            if re.match(r"^emulator-\d+\s+device", line):
                serials.append(line.split()[0])
        return serials

    def getprop(self, serial, key):
        """Doc mot property cua device."""
        out = self._run([self.adb, "-s", serial, "shell", "getprop", key])
        return out.strip()

    def avd_name_of_serial(self, serial):
        """Xac dinh AVD nao dang chay cho serial."""
        name = self.getprop(serial, "ro.boot.qemu.avd_name")
        return name if name else None

    def is_booted(self, serial):
        """Kiem tra device da boot xong chua."""
        val = self.getprop(serial, "sys.boot_completed")
        return val == "1"

    def avd_status(self):
        """Tra ve dict: {avd_name: {'running': bool, 'serial': str/None, 'booted': bool}}"""
        serials = self.running_serials()
        result = {}
        for avd in self.list_avds():
            result[avd] = {"running": False, "serial": None, "booted": False}

        # map serial -> avd
        for serial in serials:
            name = self.avd_name_of_serial(serial)
            if name and name in result:
                result[name]["running"] = True
                result[name]["serial"] = serial
                result[name]["booted"] = self.is_booted(serial)
            else:
                # AVD khong nam trong list (vd rom khac) -> ghi nhan serial tu do
                # Khong them de tranh nhieu, bo qua.
                pass
        return result

    # ---------- thao tác ----------
    def boot_avd(self, avd_name):
        """Khoi dong AVD (khong cho)."""
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = 0x08000000
            subprocess.Popen(
                [self.emulator, "-avd", avd_name],
                creationflags=creationflags,
            )
            return True
        except Exception as e:
            return f"ERROR: {e}"

    def serial_to_booted(self, avd_name, timeout=180, poll=3):
        """Khoi dong AVD va cho den khi boot xong. Tra ve serial hoac None."""
        self.boot_avd(avd_name)
        deadline = time.time() + timeout
        while time.time() < deadline:
            serials = self.running_serials()
            for s in serials:
                if self.avd_name_of_serial(s) == avd_name and self.is_booted(s):
                    return s
            time.sleep(poll)
        return None
