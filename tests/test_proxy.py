from core.models import CommandResult
from core.proxy import ProxyManager


class FakeEmulator:
    adb = "adb"

    def __init__(self):
        self.value = "null"

    def _run(self, command, timeout=30):
        if "put" in command:
            self.value = command[-1]
            return CommandResult(True, 0, "", "")
        if "get" in command:
            return CommandResult(True, 0, self.value, "")
        return CommandResult(False, 1, "", "unexpected")


def test_set_proxy_verifies_readback():
    emulator = FakeEmulator()
    proxy = ProxyManager(emulator)
    result = proxy.set_proxy("emulator-5554", "10.0.2.2:8081")
    assert result.success
    assert result.proxy == "10.0.2.2:8081"
