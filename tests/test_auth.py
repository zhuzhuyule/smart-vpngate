"""Unit tests for the web auth gate."""

from __future__ import annotations

from smart_vpngate.auth import Auth, parse_cookies, session_token


def test_disabled_when_no_password():
    a = Auth(password="", secret_path="s")
    assert not a.enabled
    assert a.authed("")           # no gate -> always authed


def test_login_success_and_cookie_roundtrip():
    a = Auth(password="hunter2", secret_path="EJsW2EeBo9lY")
    assert a.enabled
    token = a.login("hunter2")
    assert token == session_token("hunter2")
    assert a.valid_token(token)
    assert a.authed(f"session={token}")
    assert a.cookie_header(token).startswith(f"session={token}; Path=/EJsW2EeBo9lY/")


def test_login_wrong_password():
    a = Auth(password="hunter2", secret_path="s")
    assert a.login("nope") is None
    assert not a.authed("session=deadbeef")


def test_session_expiry():
    now = [1000.0]
    a = Auth(password="p", secret_path="s", ttl=100, clock=lambda: now[0])
    token = a.login("p")
    assert a.valid_token(token)
    now[0] = 1050.0
    assert a.valid_token(token)          # still within ttl
    now[0] = 1200.0
    assert not a.valid_token(token)      # expired
    assert not a.authed(f"session={token}")


def test_prefix():
    assert Auth("p", "abc").prefix == "/abc"
    assert Auth("p", "/abc/").prefix == "/abc"
    assert Auth("", "abc").prefix == "/abc"


def test_parse_cookies():
    assert parse_cookies("a=1; session=xyz; b=2") == {"a": "1", "session": "xyz", "b": "2"}
    assert parse_cookies("") == {}
