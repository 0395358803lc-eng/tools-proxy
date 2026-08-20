# -*- coding: utf-8 -*-
"""
HTTP <-> SOCKS5 bridge for Android emulator.
Runs on the HOST. The Android http_proxy global setting only speaks HTTP,
so this bridge accepts HTTP proxy requests (plain HTTP + HTTPS CONNECT) from
the emulator and forwards them through a remote SOCKS5 proxy with auth.
Each bridge instance serves ONE SOCKS5 proxy on ONE local port, so you can run
multiple bridges (different ports + different SOCKS5) to give each emulator a
different exit IP.

Usage:
    python http2socks_bridge.py [listen_port]
    python http2socks_bridge.py [listen_port] [socks_host] [socks_port] [socks_user] [socks_pass]
"""
import socket
import threading
import sys

# ---- Configuration (co the ghi de bang doi so dong lenh) ----
SOCKS5_HOST = "14.224.225.153"
SOCKS5_PORT = 51653
SOCKS5_USER = "yAEnTj"
SOCKS5_PASS = "KMKoCt"

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

# Ghi de SOCKS5 neu co tham so tu dong lenh
if len(sys.argv) >= 5:
    SOCKS5_HOST = sys.argv[2]
    SOCKS5_PORT = int(sys.argv[3])
    SOCKS5_USER = sys.argv[4]
    SOCKS5_PASS = sys.argv[5] if len(sys.argv) >= 6 else ""

BUF_SIZE = 65536

# ---- SOCKS5 helpers ---------------------------------------------------------
def socks5_connect(sock, host, port):
    """Perform a SOCKS5 handshake with username/password auth (RFC 1928/1929)."""
    # greeting: version 5, 1 method (username/password, 0x02)
    sock.sendall(b"\x05\x01\x02")
    resp = _recv_exact(sock, 2)
    if resp[0] != 0x05 or resp[1] != 0x02:
        raise RuntimeError("SOCKS5 server did not accept username/password auth: %r" % resp)
    # auth request: 0x01, ulen, uname, plen, passwd
    u = SOCKS5_USER.encode(); p = SOCKS5_PASS.encode()
    auth = b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p
    sock.sendall(auth)
    ares = _recv_exact(sock, 2)
    if ares[0] != 0x01 or ares[1] != 0x00:
        raise RuntimeError("SOCKS5 auth failed: %r" % ares)
    # connect request: ver, cmd(1=connect), rsv(0), atyp
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
        if ip.version == 4:
            atyp, host_b = 0x01, socket.inet_aton(host)
        else:
            atyp, host_b = 0x04, socket.inet_pton(socket.AF_INET6, host)
    except ValueError:
        h = host.encode()
        atyp, host_b = 0x03, bytes([len(h)]) + h
    port_b = port.to_bytes(2, "big")
    req = b"\x05\x01\x00" + bytes([atyp]) + host_b + port_b
    sock.sendall(req)
    rep = _recv_exact(sock, 4)
    if rep[0] != 0x05 or rep[1] != 0x00:
        raise RuntimeError("SOCKS5 connect failed, reply=%r" % (rep,))
    atyp = rep[3]
    if atyp == 0x01:
        _recv_exact(sock, 4)
    elif atyp == 0x04:
        _recv_exact(sock, 16)
    elif atyp == 0x03:
        ln = _recv_exact(sock, 1)[0]
        _recv_exact(sock, ln)
    _recv_exact(sock, 2)  # port
    return True


def _recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionResetError("connection closed mid-read")
        data += chunk
    return data


# ---- Relay ---------------------------------------------------------------
def _relay(a, b):
    try:
        while True:
            data = a.recv(BUF_SIZE)
            if not data:
                break
            b.sendall(data)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_WR)
            except Exception:
                pass


def _forward_plain(client, http_req, target_host, target_port):
    """Forward a plain (non-CONNECT) absolute-form HTTP request through SOCKS5."""
    up = socket.create_connection((SOCKS5_HOST, SOCKS5_PORT), timeout=30)
    try:
        socks5_connect(up, target_host, target_port)
        up.sendall(http_req)
        up.shutdown(socket.SHUT_WR)
        while True:
            data = up.recv(BUF_SIZE)
            if not data:
                break
            client.sendall(data)
    finally:
        try:
            up.close()
        except Exception:
            pass


def handle(client):
    try:
        print("ACCEPT from %s" % (str(client.getpeername()),), flush=True)
        client.settimeout(60)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                return
            data += chunk
        head, sep, _ = data.partition(b"\r\n\r\n")
        if not sep:
            head, sep, _ = data.partition(b"\n\n")
            split_seq = b"\n\n"
        else:
            split_seq = b"\r\n\r\n"
        head, _, _ = data.partition(split_seq)
        lines = head.decode("iso-8859-1", "replace").split("\r\n")
        if not lines or not lines[0]:
            return
        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            return
        method, target = parts[0], parts[1]
        print("REQ from %s -> %s %s" % (str(client.getpeername()), method, target), flush=True)

        if method.upper() == "CONNECT":
            host, _, port_s = target.rpartition(":")
            port = int(port_s)
            up = socket.create_connection((SOCKS5_HOST, SOCKS5_PORT), timeout=30)
            try:
                socks5_connect(up, host, port)
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                t1 = threading.Thread(target=_relay, args=(client, up), daemon=True)
                t2 = threading.Thread(target=_relay, args=(up, client), daemon=True)
                t1.start(); t2.start()
                t1.join(); t2.join()
            finally:
                try:
                    up.close()
                except Exception:
                    pass
            return

        # Plain HTTP absolute-form request
        scheme = "http"
        rest = target
        if target.startswith("http://"):
            rest = target[len("http://"):]
        elif target.startswith("https://"):
            scheme = "https"
            rest = target[len("https://"):]
        host = rest
        port = 443 if scheme == "https" else 80
        if "/" in host:
            host, _, _ = host.partition("/")
        if host.startswith("["):
            hb, _, pb = host[1:].partition("]")
            host = hb
            if pb.startswith(":"):
                port = int(pb[1:])
        elif ":" in host:
            h, _, ps = host.rpartition(":")
            if ps.isdigit():
                host, port = h, int(ps)
        if not host:
            return
        _forward_plain(client, data, host, port)
    except Exception:
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        except Exception:
            pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(128)
    print("HTTP<->SOCKS5 bridge listening on %s:%d -> %s:%d (auth user=%s)" %
          (LISTEN_HOST, LISTEN_PORT, SOCKS5_HOST, SOCKS5_PORT, SOCKS5_USER), flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()

