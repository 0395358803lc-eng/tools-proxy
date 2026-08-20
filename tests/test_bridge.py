import socket
from pathlib import Path

from core.bridge import BridgeProcess
from core.models import SocksProxy
from core.state import ProxyStore


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_bridge_health_endpoint_identifies_proxy(tmp_path):
    proxy_path = tmp_path / "proxies.local.json"
    store = ProxyStore(proxy_path)
    proxy = SocksProxy("127.0.0.1", 9, "user", "secret")
    proxy_id = store.upsert(proxy)
    script = Path(__file__).resolve().parents[1] / "http2socks_bridge.py"
    bridge = BridgeProcess(script, free_port(), proxy_id, proxy_path, log_dir=tmp_path / "logs")
    ok, message = bridge.start()
    try:
        assert ok, message
        healthy, payload = bridge.probe()
        assert healthy
        assert payload["proxy_id"] == proxy_id
    finally:
        bridge.stop()
