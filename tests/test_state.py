import json

from core.models import Assignment, SocksProxy
from core.state import ProxyStore, StateStore


def test_state_and_proxy_secrets_are_separated(tmp_path):
    state_path = tmp_path / "data" / "state.json"
    proxy_path = tmp_path / "proxies.local.json"
    state = StateStore(state_path)
    proxies = ProxyStore(proxy_path)

    proxy = SocksProxy("proxy.example", 1080, "user", "super-secret")
    proxy_id = proxies.upsert(proxy)
    state.set(Assignment("Phone_01", proxy_id, 8081))

    state_text = state_path.read_text(encoding="utf-8")
    secret_text = proxy_path.read_text(encoding="utf-8")
    assert "super-secret" not in state_text
    assert "super-secret" in secret_text
    assert state.get("Phone_01").local_port == 8081


def test_update_port_for_shared_proxy(tmp_path):
    state = StateStore(tmp_path / "state.json")
    state.set(Assignment("A", "proxy_x", 8081))
    state.set(Assignment("B", "proxy_x", 8081))
    state.update_port_for_proxy("proxy_x", 8099)
    values = state.all_assignments()
    assert values["A"].local_port == 8099
    assert values["B"].local_port == 8099
