from core.emulator import EmulatorManager
from core.models import CommandResult


class FakeRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, timeout):
        command = [str(x) for x in command]
        self.commands.append(command)
        joined = " ".join(command)
        if joined.endswith("adb devices"):
            return CommandResult(True, 0, "List of devices attached\nemulator-5554\tdevice", "")
        if "ro.boot.qemu.avd_name" in joined:
            return CommandResult(True, 0, "Phone_01", "")
        if "sys.boot_completed" in joined:
            return CommandResult(True, 0, "1", "")
        return CommandResult(True, 0, "", "")


def test_wait_until_booted_never_starts_avd(tmp_path):
    runner = FakeRunner()
    manager = EmulatorManager(tmp_path, runner=runner)
    serial = manager.serial_to_booted("Phone_01", timeout=1, poll=0)
    assert serial == "emulator-5554"
    assert not any("-avd" in command for command in runner.commands)
