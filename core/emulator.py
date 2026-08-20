from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .models import CommandResult

Runner = Callable[[Sequence[str], int], CommandResult]


def run_command(command: Sequence[str], timeout: int = 60) -> CommandResult:
    cmd = tuple(str(x) for x in command)
    try:
        flags = 0x08000000 if os.name == "nt" else 0
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
        return CommandResult(
            success=proc.returncode == 0,
            return_code=proc.returncode,
            stdout=(proc.stdout or "").strip(),
            stderr=(proc.stderr or "").strip(),
            command=cmd,
        )
    except Exception as exc:
        return CommandResult(False, -1, "", str(exc), cmd)


class EmulatorManager:
    def __init__(self, sdk_path: str | Path, runner: Runner | None = None):
        self.sdk = Path(sdk_path)
        suffix = ".exe" if os.name == "nt" else ""
        self.adb = self.sdk / "platform-tools" / f"adb{suffix}"
        self.emulator = self.sdk / "emulator" / f"emulator{suffix}"
        self._runner = runner or run_command

    def _run(self, command: Sequence[str], timeout: int = 60) -> CommandResult:
        return self._runner([str(x) for x in command], timeout)

    def validate_sdk(self) -> tuple[bool, str]:
        missing = [str(path) for path in (self.adb, self.emulator) if not path.exists()]
        if missing:
            return False, "missing Android SDK executable(s): " + ", ".join(missing)
        return True, "ok"

    def list_avds(self) -> list[str]:
        result = self._run([self.emulator, "-list-avds"])
        if not result.success:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def running_serials(self) -> list[str]:
        result = self._run([self.adb, "devices"])
        if not result.success:
            return []
        serials: list[str] = []
        for line in result.stdout.splitlines():
            if re.match(r"^emulator-\d+\s+device(?:\s|$)", line.strip()):
                serials.append(line.split()[0])
        return serials

    def getprop(self, serial: str, key: str) -> str:
        result = self._run([self.adb, "-s", serial, "shell", "getprop", key], timeout=30)
        return result.stdout.strip() if result.success else ""

    def avd_name_of_serial(self, serial: str) -> str | None:
        name = self.getprop(serial, "ro.boot.qemu.avd_name")
        return name or None

    def is_booted(self, serial: str) -> bool:
        return self.getprop(serial, "sys.boot_completed") == "1"

    def serial_for_avd(self, avd_name: str, require_booted: bool = False) -> str | None:
        for serial in self.running_serials():
            if self.avd_name_of_serial(serial) != avd_name:
                continue
            if require_booted and not self.is_booted(serial):
                continue
            return serial
        return None

    def avd_status(self) -> dict[str, dict]:
        result = {
            avd: {"running": False, "serial": None, "booted": False}
            for avd in self.list_avds()
        }
        for serial in self.running_serials():
            name = self.avd_name_of_serial(serial)
            if not name:
                continue
            result.setdefault(name, {"running": False, "serial": None, "booted": False})
            result[name].update(
                {"running": True, "serial": serial, "booted": self.is_booted(serial)}
            )
        return result

    def boot_avd(self, avd_name: str) -> CommandResult:
        if self.serial_for_avd(avd_name):
            return CommandResult(True, 0, f"{avd_name} is already running", "", ())
        command = (str(self.emulator), "-avd", avd_name)
        try:
            flags = 0x08000000 if os.name == "nt" else 0
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
            return CommandResult(True, 0, f"boot command sent for {avd_name}", "", command)
        except Exception as exc:
            return CommandResult(False, -1, "", str(exc), command)

    def wait_until_booted(self, avd_name: str, timeout: int = 180, poll: float = 3.0) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            serial = self.serial_for_avd(avd_name, require_booted=True)
            if serial:
                return serial
            time.sleep(poll)
        return None

    def serial_to_booted(self, avd_name: str, timeout: int = 180, poll: float = 3.0) -> str | None:
        """Backward-compatible alias. It no longer boots the AVD a second time."""
        return self.wait_until_booted(avd_name, timeout=timeout, poll=poll)
