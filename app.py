from __future__ import annotations

import argparse
import json
import signal
import sys
import time

from core.models import SocksProxy
from core.runtime import build_runtime


def cmd_list(runtime, _args) -> int:
    rows = runtime.emulators.avd_status()
    assignments = runtime.state.all_assignments()
    for avd, info in rows.items():
        assignment = assignments.get(avd)
        proxy_id = assignment.proxy_id if assignment else "-"
        port = assignment.local_port if assignment else "-"
        print(
            f"{avd}\trunning={info['running']}\tbooted={info['booted']}\t"
            f"serial={info['serial'] or '-'}\tproxy_id={proxy_id}\tport={port}"
        )
    return 0


def cmd_status(runtime, _args) -> int:
    report = runtime.supervisor.supervise_once()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if not any(kind.endswith("error") for kind, _ in report.get("actions", [])) else 2


def cmd_boot(runtime, args) -> int:
    result = runtime.emulators.boot_avd(args.avd)
    if not result.success:
        print(result.error, file=sys.stderr)
        return 2
    print(result.stdout)
    serial = runtime.emulators.wait_until_booted(
        args.avd, timeout=runtime.config.boot_timeout_sec, poll=3
    )
    if not serial:
        print(f"{args.avd} did not finish booting", file=sys.stderr)
        return 3
    expected = runtime.registry.proxy_for_avd(args.avd)
    if expected:
        runtime.registry.ensure_all()
        restored = runtime.proxy.ensure_proxy(serial, expected)
        if not restored.success:
            print(restored.error, file=sys.stderr)
            return 4
    print(f"{args.avd} ready on {serial}")
    return 0


def cmd_assign(runtime, args) -> int:
    try:
        parsed = SocksProxy.parse(args.proxy)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    proxy_id = runtime.proxies.upsert(parsed)
    ok, message, port = runtime.registry.assign(args.avd, proxy_id)
    if not ok or port is None:
        print(message, file=sys.stderr)
        return 3
    serial = runtime.emulators.serial_for_avd(args.avd, require_booted=True)
    expected = runtime.registry.proxy_for_avd(args.avd)
    if serial and expected:
        result = runtime.proxy.set_proxy(serial, expected)
        if not result.success:
            print(result.error, file=sys.stderr)
            return 4
    print(f"assigned {args.avd} -> {parsed.redacted()} via {runtime.config.emulator_gateway}:{port}")
    return 0


def cmd_remove(runtime, args) -> int:
    serial = runtime.emulators.serial_for_avd(args.avd, require_booted=True)
    if serial:
        runtime.proxy.remove_proxy(serial)
    ok, message = runtime.registry.remove(args.avd)
    print(message)
    return 0 if ok else 2


def cmd_test(runtime, args) -> int:
    port = runtime.registry.port_for_avd(args.avd)
    if port is None:
        print(f"{args.avd} has no proxy assignment", file=sys.stderr)
        return 2
    runtime.registry.ensure_all()
    ok, detail = runtime.proxy.test_proxy_port(port, runtime.config.proxy_test_url)
    if ok:
        print(f"bridge exit IP: {detail}")
        return 0
    print(detail, file=sys.stderr)
    return 3


def cmd_supervisor(runtime, _args) -> int:
    stopping = False

    def stop_handler(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_handler)

    def callback(report):
        for kind, message in report.get("actions", []):
            print(f"[{report.get('timestamp', '-')}] {kind}: {message}", flush=True)

    runtime.supervisor.callback = callback
    runtime.supervisor.start()
    print("tools-proxy supervisor running", flush=True)
    try:
        while not stopping:
            time.sleep(0.5)
    finally:
        runtime.supervisor.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Android Emulator Proxy Manager CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("status").set_defaults(func=cmd_status)

    boot = sub.add_parser("boot")
    boot.add_argument("avd")
    boot.set_defaults(func=cmd_boot)

    assign = sub.add_parser("assign")
    assign.add_argument("avd")
    assign.add_argument("proxy", help="socks5://user:pass@host:port or legacy host:port:user:pass")
    assign.set_defaults(func=cmd_assign)

    remove = sub.add_parser("remove")
    remove.add_argument("avd")
    remove.set_defaults(func=cmd_remove)

    test = sub.add_parser("test")
    test.add_argument("avd")
    test.set_defaults(func=cmd_test)

    sub.add_parser("supervisor").set_defaults(func=cmd_supervisor)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    runtime = build_runtime()
    return int(args.func(runtime, args))


if __name__ == "__main__":
    raise SystemExit(main())
