from core.autostart import Supervisor
from core.models import Assignment, ProxyResult


class FakeState:
    def all_assignments(self):
        return {"Phone_01": Assignment("Phone_01", "proxy_x", 8081)}


class FakeRegistry:
    def ensure_all(self):
        return []

    def health(self):
        return {"proxy_x": {"port": 8081, "healthy": True}}

    def proxy_for_avd(self, avd):
        return "10.0.2.2:8081"


class FakeEmulators:
    def avd_status(self):
        return {
            "Phone_01": {
                "running": True,
                "booted": True,
                "serial": "emulator-5554",
            }
        }


class FakeProxy:
    def __init__(self):
        self.set_calls = []

    def get_proxy(self, serial):
        return ProxyResult(True, proxy="null")

    def set_proxy(self, serial, expected):
        self.set_calls.append((serial, expected))
        return ProxyResult(True, proxy=expected)


def test_supervisor_restores_null_proxy():
    proxy = FakeProxy()
    supervisor = Supervisor(FakeRegistry(), FakeEmulators(), proxy, FakeState(), interval=1)
    report = supervisor.supervise_once()
    assert proxy.set_calls == [("emulator-5554", "10.0.2.2:8081")]
    assert ("proxy", "Phone_01: restored 10.0.2.2:8081") in report["actions"]
