"""Recall gaps found in the 2026-10-19 audit: quoted/URL/provider secrets, IPv4, 91-prefixed phones, Aadhaar VIDs."""

import pytest

from seen_core.pii import validators as v
from seen_core.pii.detect import scan

VID = "234567890123456" + v.verhoeff_digit("234567890123456")


def types(text: str) -> set[str]:
    return {f.type for f in scan(text, min_confidence="medium")}


@pytest.mark.parametrize("text", [
    '{"api_key": "' + "Xk9Lm2Qp7Rt4Vw8Zb3Nc" + '"}',
    'password: "' + "S3cr3t!x9Qm#7Lp2" + '"',
    "DB_PASSWORD=" + "Xk9$mQ2!vL7#pR4z",
    "postgres://app_user:" + "Zq8mK2xLp9" + "@db.internal:5432/app",
    "key " + "AIza" + "SyD3x9Qm2LpR7vK1nB8cT4wZ6yH0jF5gE_a",
    "stripe " + "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc",
    "Authorization: Bearer " + "q8Zk2mXpL9vR4tYw7NcB3hJd",
    "token " + "glpat-" + "x8Zk2mXpL9vR4tYw7NcB",
])
def test_secret_forms_are_found(text: str) -> None:
    assert "secret" in types(text)


@pytest.mark.parametrize("text", [
    "password: changeme", "api_key = get_api_key()", "token_count: 1234567890123456", "key: value",
    "postgres://user:password@localhost/db", "postgres://user:${DB_PASS}@host/db", "https://example.com/a:b@c",
])
def test_secret_lookalikes_are_not(text: str) -> None:
    assert "secret" not in types(text)


def test_public_ipv4_found_private_and_docs_ranges_not() -> None:
    assert "ip" in types("client 52.95.110.1 failed login")
    for ip in ("10.0.0.5", "127.0.0.1", "192.168.1.20", "192.0.2.4", "8.8.8.8", "0.0.0.0", "999.1.1.1"):
        assert "ip" not in types(f"host {ip} up"), ip
    assert "ip" not in types("version 1.2.3.4.5 released")


def test_country_code_phone_without_plus() -> None:
    assert "phone" in types("call 919876543210 now")


def test_aadhaar_vid_found() -> None:
    assert "aadhaar" in types(f"my VID is {VID}")
