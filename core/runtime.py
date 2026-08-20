from __future__ import annotations

from dataclasses import dataclass

from .autostart import Supervisor
from .bridge import BridgeRegistry
from .config import AppConfig, load_config
from .emulator import EmulatorManager
from .proxy import ProxyManager
from .state import ProxyStore, StateStore


@dataclass(slots=True)
class Runtime:
    config: AppConfig
    emulators: EmulatorManager
    proxy: ProxyManager
    state: StateStore
    proxies: ProxyStore
    registry: BridgeRegistry
    supervisor: Supervisor


def build_runtime(base_dir=None, callback=None) -> Runtime:
    config = load_config(base_dir)
    emulators = EmulatorManager(config.sdk_path)
    proxy = ProxyManager(emulators)
    state = StateStore(config.state_path)
    proxies = ProxyStore(config.proxy_store_path)
    registry = BridgeRegistry(
        config.bridge_script,
        state,
        proxies,
        config.proxy_store_path,
        port_base=config.port_base,
        bind_host=config.bridge_bind_host,
        emulator_gateway=config.emulator_gateway,
        log_dir=config.log_dir,
    )
    supervisor = Supervisor(
        registry,
        emulators,
        proxy,
        state,
        interval=config.supervisor_interval_sec,
        callback=callback,
    )
    return Runtime(config, emulators, proxy, state, proxies, registry, supervisor)
