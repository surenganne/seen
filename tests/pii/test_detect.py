import time

import pytest

from seen_core.pii import validators as v
from seen_core.pii.detect import scan

AADHAAR = "23456789012" + v.verhoeff_digit("23456789012")


def luhn_complete(base: str) -> str:
    return next(base + str(d) for d in range(10) if v.luhn_valid(base + str(d)))


CARD = luhn_complete("531268001234567")


def types(text: str, **kw: object) -> dict[str, str]:
    return {f.type: f.confidence for f in scan(text, **kw)}  # type: ignore[arg-type]


@pytest.mark.parametrize("text,typ,conf", [
    (f"Aadhaar {AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}", "aadhaar", "high"),
    ("contact: sentinel.person@corp.test.in", "email", "medium"),
    ("PAN ABCPE1234F on file", "pan", "medium"),
    (f"card {CARD[:4]} {CARD[4:8]} {CARD[8:12]} {CARD[12:]} expires", "card", "high"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "iban", "high"),
    ("SSN 123-45-6789", "ssn", "medium"),
    ("pay to ravi.k@okaxis today", "upi", "medium"),
    ("dob: 12/03/1990", "dob", "medium"),
    ("mobile +91 98765 43210", "phone", "medium"),
    ("GSTIN 27AAPFU0939F1ZV", "gstin", "medium"),
    ("AKIAIOSFODNN7EXAMPLA", "secret", "high"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIE", "secret", "high"),
    ("api_key = 'q8ZtK2mV9xLp4RwN7cYbHs3D'", "secret", "medium"),
])
def test_positives(text: str, typ: str, conf: str) -> None:
    assert types(text).get(typ) == conf, scan(text)


@pytest.mark.parametrize("text", [
    "order 23456789 0123 shipped",                    # 12 digits, fails Verhoeff
    "Visa test card 4111 1111 1111 1111",           # well-known test card
    "Stripe 4242 4242 4242 4242",
    "uuid 123e4567-e89b-12d3-a456-426614174000",
    "build 2026.10.18 sha 4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "user@example.com and admin@example.org",        # RFC 2606 docs domains
    "version 9876543210 of the schema",              # 10 digits without phone context: low only
    "ticket ABCDE12345",
    "date 2026-10-18 deploy",                        # date without a DOB keyword
])
def test_hard_negatives(text: str) -> None:
    found = {f.type: f.confidence for f in scan(text) if f.confidence != "low"}
    assert not found, (text, found)


def test_counts_distinct_and_fingerprints_never_values() -> None:
    text = "a@corp.test.in, b@corp.test.in, a@corp.test.in"
    f = next(x for x in scan(text) if x.type == "email")
    assert (f.count, f.distinct) == (3, 2)
    assert all(len(fp) == 16 for fp in f.fingerprints) and "corp" not in "".join(f.fingerprints)
    assert scan(text)[0].fingerprints == scan(text)[0].fingerprints  # stable per install


def test_allow_values_and_types_filter() -> None:
    assert "email" not in types("x@corp.test.in", allow_values=["*@corp.test.in"])
    assert types(f"{AADHAAR} x@corp.test.in", only=["email"]).keys() == {"email"}


def test_custom_rule() -> None:
    rules = [{"id": "mrn", "type": "custom", "pattern": r"\bMRN[:# ]*\d{6,10}\b", "confidence": "medium"}]
    f = [x for x in scan("Patient MRN: 00123456", custom_rules=rules) if x.type == "custom"]
    assert f and f[0].detector == "custom:mrn"


def test_10k_prompt_under_30ms() -> None:
    text = ("lorem ipsum dolor sit amet 1234 " * 300)[:10_000] + f" {AADHAAR}"
    scan(text)
    t = time.perf_counter()
    for _ in range(5):
        scan(text)
    assert (time.perf_counter() - t) / 5 * 1000 < 30


@pytest.mark.parametrize("evil", ["key." * 2500, "a" * 10000 + "key", "token" * 2000 + "=", "x@" * 5000, "1 " * 5000])
def test_adversarial_input_stays_fast(evil: str) -> None:
    t = time.perf_counter()
    scan(evil)
    assert (time.perf_counter() - t) * 1000 < 100


@pytest.mark.parametrize("pattern", ["*", "*@*", "*.*", "**", "?*@*"])
def test_overbroad_allow_patterns_ignored(pattern: str) -> None:
    assert "email" in types("mail x.person@corp.test.in", allow_values=[pattern])


def test_allowlist_never_suppresses_secrets() -> None:
    assert "secret" in types("AKIAIOSFODNN7EXAMPLA", allow_values=["AKIA*", "akia*"])


def test_allowlisted_count_reported() -> None:
    from seen_core.pii.detect import scan_with_stats

    found, allowed = scan_with_stats("a@corp.test.in b@corp.test.in", allow_values=["*@corp.test.in"])
    assert not found and allowed == 2


@pytest.mark.parametrize("pattern", ["[a-z][a-z][a-z][a-z]*@*", "????*", "*abcd*", "a*b*c*d*e", "*@*.in"])
def test_glob_tricks_rejected(pattern: str) -> None:
    from seen_core.pii.detect import usable_patterns

    assert usable_patterns([pattern]) == []


def test_exact_and_suffix_patterns_kept() -> None:
    from seen_core.pii.detect import usable_patterns

    assert usable_patterns(["*@example.com", "qa.bot@corp.test.in", "*.test.local"]) == ["*@example.com", "qa.bot@corp.test.in", "*.test.local"]
