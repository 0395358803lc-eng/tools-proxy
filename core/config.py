from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _find_sdk(configured: str) -> Path:
    candidates = [configured, os.getenv("ANDROID_SDK_ROOT", ""), os.getenv("ANDROID_HOME", "")]
    if os.name == "nt":
        local = os.getenv("LOCALAPPDATA", "")
        if local:
            candidates.append(str(Path(local) / "Android" / "Sdk"))
    for raw in candidates:
        if raw and Path(raw).expanduser().exists():
            return Path(raw).expanduser().resolve()
    return Path(configured).expanduser() if configured else Path()


@dataclass(frozen=True, slots=True)
class AppConfig:
    base_dir: Path
    sdk_path: Path
    bridge_script: Path
    bridge_bind_host: str
    port_base: int
    emulator_gateway: str
    supervisor_interval_sec: int
    boot_timeout_sec: int
    proxy_test_url: str
    state_path: Path
    proxy_store_path: Path
    log_dir: Path

    @property
    def adb_path(self) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return self.sdk_path / "platform-tools" / f"adb{suffix}"

    @property
    def emulator_path(self) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return self.sdk_path / "emulator" / f"emulator{suffix}"


def load_config(base_dir: str | Path | None = None) -> AppConfig:
    root = Path(base_dir or Path(__file__).resolve().parents[1]).resolve()
    merged: dict[str, Any] = {
        "sdk_path": "",
        "bridge_bind_host": "127.0.0.1",
        "port_base": 8081,
        "emulator_gateway": "10.0.2.2",
        "supervisor_interval_sec": 10,
        "boot_timeout_sec": 180,
        "proxy_test_url": "http://api.ipify.org",
    }
    merged.update(_load_json(root / "config.json"))
    merged.update(_load_json(root / "config.local.json"))

    env_map = {
        "TOOLS_PROXY_SDK_PATH": "sdk_path",
        "TOOLS_PROXY_BIND_HOST": "bridge_bind_host",
        "TOOLS_PROXY_PORT_BASE": "port_base",
        "TOOLS_PROXY_GATEWAY": "emulator_gateway",
        "TOOLS_PROXY_SUPERVISOR_INTERVAL": "supervisor_interval_sec",
        "TOOLS_PROXY_BOOT_TIMEOUT": "boot_timeout_sec",
        "TOOLS_PROXY_TEST_URL": "proxy_test_url",
    }
    for env_name, key in env_map.items():
        value = os.getenv(env_name)
        if value is not None and value != "":
            merged[key] = value

    for key in ("port_base", "supervisor_interval_sec", "boot_timeout_sec"):
        merged[key] = int(merged[key])

    sdk = _find_sdk(str(merged.get("sdk_path", "")))
    return AppConfig(
        base_dir=root,
        sdk_path=sdk,
        bridge_script=root / "http2socks_bridge.py",
        bridge_bind_host=str(merged["bridge_bind_host"]),
        port_base=int(merged["port_base"]),
        emulator_gateway=str(merged["emulator_gateway"]),
        supervisor_interval_sec=int(merged["supervisor_interval_sec"]),
        boot_timeout_sec=int(merged["boot_timeout_sec"]),
        proxy_test_url=str(merged["proxy_test_url"]),
        state_path=root / "data" / "state.json",
        proxy_store_path=root / "proxies.local.json",
        log_dir=root / "logs",
    )
