from core.models import SocksProxy


def test_parse_uri_and_redaction():
    proxy = SocksProxy.parse("socks5://alice:p%40ss@example.com:1080")
    assert proxy.host == "example.com"
    assert proxy.port == 1080
    assert proxy.username == "alice"
    assert proxy.password == "p@ss"
    assert "p@ss" not in proxy.redacted()
    assert proxy.proxy_id.startswith("proxy_")


def test_parse_legacy_password_with_colons():
    proxy = SocksProxy.parse("127.0.0.1:1080:user:p:a:s:s")
    assert proxy.password == "p:a:s:s"


def test_parse_ipv6_uri():
    proxy = SocksProxy.parse("socks5://u:p@[2001:db8::1]:1080")
    assert proxy.host == "2001:db8::1"
    assert proxy.to_uri().endswith("@[2001:db8::1]:1080")
