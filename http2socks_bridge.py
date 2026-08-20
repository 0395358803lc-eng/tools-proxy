from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

BUF_SIZE = 65536
MAX_HEADER = 65536
LOGGER = logging.getLogger("tools_proxy.bridge")


def load_proxy(proxy_file: str | Path, proxy_id: str) -> dict:
    path = Path(proxy_file)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    item = data.get("proxies", {}).get(proxy_id)
    if not isinstance(item, dict):
        raise RuntimeError(f"proxy id {proxy_id!r} not found in {path}")
    return {
        "host": str(item["host"]),
        "port": int(item["port"]),
        "username": str(item.get("username", "")),
        "password": str(item.get("password", "")),
    }


def recv_exact(sock: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionResetError("connection closed mid-read")
        data.extend(chunk)
    return bytes(data)


def socks5_connect(sock: socket.socket, target_host: str, target_port: int, proxy: dict) -> None:
    methods = [0x00]
    if proxy["username"] or proxy["password"]:
        methods = [0x02]
    sock.sendall(bytes([0x05, len(methods), *methods]))
    response = recv_exact(sock, 2)
    if response[0] != 0x05 or response[1] == 0xFF:
        raise RuntimeError("SOCKS5 server rejected authentication methods")

    if response[1] == 0x02:
        user = proxy["username"].encode("utf-8")
        password = proxy["password"].encode("utf-8")
        if len(user) > 255 or len(password) > 255:
            raise RuntimeError("SOCKS5 username/password exceeds RFC 1929 limit")
        sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(password)]) + password)
        auth_response = recv_exact(sock, 2)
        if auth_response != b"\x01\x00":
            raise RuntimeError("SOCKS5 authentication failed")
    elif response[1] != 0x00:
        raise RuntimeError(f"unsupported SOCKS5 authentication method {response[1]}")

    try:
        packed = socket.inet_pton(socket.AF_INET, target_host)
        address = b"\x01" + packed
    except OSError:
        try:
            packed = socket.inet_pton(socket.AF_INET6, target_host)
            address = b"\x04" + packed
        except OSError:
            encoded = target_host.encode("idna")
            if len(encoded) > 255:
                raise RuntimeError("target hostname is too long")
            address = b"\x03" + bytes([len(encoded)]) + encoded

    sock.sendall(b"\x05\x01\x00" + address + int(target_port).to_bytes(2, "big"))
    reply = recv_exact(sock, 4)
    if reply[0] != 0x05 or reply[1] != 0x00:
        raise RuntimeError(f"SOCKS5 connect failed with reply code {reply[1]}")
    atyp = reply[3]
    if atyp == 0x01:
        recv_exact(sock, 4)
    elif atyp == 0x04:
        recv_exact(sock, 16)
    elif atyp == 0x03:
        recv_exact(sock, recv_exact(sock, 1)[0])
    else:
        raise RuntimeError("invalid SOCKS5 bind address type")
    recv_exact(sock, 2)


def relay(source: socket.socket, target: socket.socket) -> None:
    try:
        while True:
            chunk = source.recv(BUF_SIZE)
            if not chunk:
                break
            target.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def read_request(client: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = client.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_HEADER:
            raise RuntimeError("HTTP request headers exceed limit")
    return bytes(data)


def send_health(client: socket.socket, proxy_id: str, listen_host: str, listen_port: int) -> None:
    body = json.dumps(
        {
            "service": "tools-proxy-bridge",
            "proxy_id": proxy_id,
            "listen_host": listen_host,
            "listen_port": listen_port,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    response = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
        + body
    )
    client.sendall(response)


def parse_target(request_line: str, headers: list[str]) -> tuple[str, int, str, str]:
    parts = request_line.split(" ", 2)
    if len(parts) != 3:
        raise RuntimeError("invalid HTTP request line")
    method, target, version = parts
    if method.upper() == "CONNECT":
        if target.startswith("["):
            host_part, _, port_part = target[1:].partition("]:")
            return host_part, int(port_part), method, target
        host, sep, port_raw = target.rpartition(":")
        if not sep:
            raise RuntimeError("CONNECT target must contain a port")
        return host, int(port_raw), method, target

    parsed = urlsplit(target)
    if parsed.scheme and parsed.hostname:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.hostname, port, method, target

    host_header = ""
    for header in headers:
        if header.lower().startswith("host:"):
            host_header = header.split(":", 1)[1].strip()
            break
    if not host_header:
        raise RuntimeError("request is missing Host header")
    if host_header.startswith("["):
        host, _, tail = host_header[1:].partition("]")
        port = int(tail[1:]) if tail.startswith(":") else 80
    elif ":" in host_header and host_header.rsplit(":", 1)[1].isdigit():
        host, port_raw = host_header.rsplit(":", 1)
        port = int(port_raw)
    else:
        host, port = host_header, 80
    return host, port, method, target


def rewrite_absolute_request(data: bytes) -> bytes:
    head, separator, rest = data.partition(b"\r\n")
    try:
        method, target, version = head.decode("iso-8859-1").split(" ", 2)
    except ValueError:
        return data
    parsed = urlsplit(target)
    if not parsed.scheme or not parsed.hostname:
        return data
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return f"{method} {path} {version}".encode("iso-8859-1") + separator + rest


def handle_client(
    client: socket.socket,
    proxy: dict,
    proxy_id: str,
    listen_host: str,
    listen_port: int,
    connection_slots: threading.BoundedSemaphore | None = None,
) -> None:
    try:
        client.settimeout(60)
        data = read_request(client)
        if not data:
            return
        header_text = data.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1", "replace")
        lines = header_text.split("\r\n")
        request_line = lines[0]
        host, port, method, target = parse_target(request_line, lines[1:])

        if host == "proxy.local" and target.startswith("http://proxy.local/__health__"):
            send_health(client, proxy_id, listen_host, listen_port)
            return

        upstream = socket.create_connection((proxy["host"], proxy["port"]), timeout=30)
        upstream.settimeout(60)
        try:
            socks5_connect(upstream, host, port, proxy)
            if method.upper() == "CONNECT":
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                first = threading.Thread(target=relay, args=(client, upstream), daemon=True)
                second = threading.Thread(target=relay, args=(upstream, client), daemon=True)
                first.start()
                second.start()
                first.join()
                second.join()
            else:
                upstream.sendall(rewrite_absolute_request(data))
                while True:
                    chunk = upstream.recv(BUF_SIZE)
                    if not chunk:
                        break
                    client.sendall(chunk)
        finally:
            upstream.close()
    except Exception as exc:
        LOGGER.warning("request failed on bridge %s: %s", proxy_id, exc)
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass
    finally:
        try:
            client.close()
        except OSError:
            pass
        if connection_slots is not None:
            connection_slots.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local HTTP to authenticated SOCKS5 bridge")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--proxy-file", required=True)
    parser.add_argument("--proxy-id", required=True)
    parser.add_argument("--max-connections", type=int, default=256)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    proxy = load_proxy(args.proxy_file, args.proxy_id)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(128)
    server.settimeout(1.0)
    stop_event = threading.Event()
    slots = threading.BoundedSemaphore(max(1, args.max_connections))

    def request_stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    LOGGER.info(
        "bridge started proxy_id=%s listen=%s:%s max_connections=%s",
        args.proxy_id, args.listen_host, args.listen_port, args.max_connections,
    )
    try:
        while not stop_event.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            if not slots.acquire(blocking=False):
                try:
                    client.sendall(
                        b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                finally:
                    client.close()
                continue
            threading.Thread(
                target=handle_client,
                args=(client, proxy, args.proxy_id, args.listen_host, args.listen_port, slots),
                daemon=True,
            ).start()
    finally:
        server.close()
        LOGGER.info("bridge stopped proxy_id=%s listen_port=%s", args.proxy_id, args.listen_port)


if __name__ == "__main__":
    main()
