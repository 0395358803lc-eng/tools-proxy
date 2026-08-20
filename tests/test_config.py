import json

from core.config import load_config


def test_config_local_overrides_and_env(tmp_path, monkeypatch):
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    (tmp_path / "config.json").write_text(
        json.dumps({"port_base": 9000, "supervisor_interval_sec": 20}), encoding="utf-8"
    )
    (tmp_path / "config.local.json").write_text(
        json.dumps({"port_base": 9001}), encoding="utf-8"
    )
    monkeypatch.setenv("TOOLS_PROXY_SDK_PATH", str(sdk))
    monkeypatch.setenv("TOOLS_PROXY_SUPERVISOR_INTERVAL", "7")

    config = load_config(tmp_path)
    assert config.port_base == 9001
    assert config.supervisor_interval_sec == 7
    assert config.sdk_path == sdk.resolve()
    assert config.bridge_bind_host == "127.0.0.1"
