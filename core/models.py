from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from urllib.parse import quote, unquote, urlsplit


@dataclass(slots=True)
class CommandResult:
    success: bool
    return_code: int
    stdout: str = ""
    stderr: str = ""
    command: tuple[str, ...] = ()

    @property
    def error(self) -> str | None:
        if self.success:
            return None
        return self.stderr.strip() or self.stdout.strip() or f"command failed ({self.return_code})"


@dataclass(frozen=True, slots=True)
class SocksProxy:
    host: str
    port: int
    username: str
    password: str

    @classmethod
    def parse(cls, raw: str) -> SocksProxy:
        value = raw.strip()
        if not value:
            raise ValueError("proxy is empty")

        if "://" in value:
            parsed = urlsplit(value)
            if parsed.scheme.lower() not in {"socks5", "socks5h"}:
                raise ValueError("proxy URI must use socks5:// or socks5h://")
            if not parsed.hostname or parsed.port is None:
                raise ValueError("proxy URI must contain host and port")
            return cls(
                host=parsed.hostname,
                port=parsed.port,
                username=unquote(parsed.username or ""),
                password=unquote(parsed.password or ""),
            )

        # Backward-compatible legacy format: host:port:user:password-with-colons
        parts = value.split(":")
        if len(parts) < 4:
            raise ValueError("use socks5://user:pass@host:port or host:port:user:pass")
        host, port_raw, username = parts[0], parts[1], parts[2]
        if not host:
            raise ValueError("proxy host is empty")
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError("proxy port must be an integer") from exc
        return cls(host=host, port=port, username=username, password=":".join(parts[3:]))

    @property
    def proxy_id(self) -> str:
        digest = sha256(
            f"{self.host}\0{self.port}\0{self.username}\0{self.password}".encode()
        ).hexdigest()
        return f"proxy_{digest[:12]}"

    def to_uri(self) -> str:
        user = quote(self.username, safe="")
        password = quote(self.password, safe="")
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"socks5://{user}:{password}@{host}:{self.port}"

    def redacted(self) -> str:
        user = self.username[:2] + "***" if self.username else ""
        return f"{self.host}:{self.port} user={user or '-'}"

    def as_secret_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ProxyResult:
    success: bool
    proxy: str | None = None
    error: str | None = None


@dataclass(slots=True)
class Assignment:
    avd: str
    proxy_id: str
    local_port: int

    def as_dict(self) -> dict:
        return {"proxy_id": self.proxy_id, "local_port": self.local_port}
