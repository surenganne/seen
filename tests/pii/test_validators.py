import pytest

from seen_core.pii import validators as v


@pytest.mark.parametrize("s,ok", [("2363", True), ("2364", False), ("0", True)])
def test_verhoeff(s: str, ok: bool) -> None:
    assert v.verhoeff_valid(s) is ok


def test_verhoeff_check_digit_roundtrip() -> None:
    for base in ("23", "23456789012", "98765432101"):
        assert v.verhoeff_valid(base + v.verhoeff_digit(base))


@pytest.mark.parametrize("s,ok", [("79927398713", True), ("79927398710", False), ("4111111111111111", True)])
def test_luhn(s: str, ok: bool) -> None:
    assert v.luhn_valid(s) is ok


@pytest.mark.parametrize("s,ok", [("GB82WEST12345698765432", True), ("DE89370400440532013000", True), ("GB82WEST12345698765433", False)])
def test_iban(s: str, ok: bool) -> None:
    assert v.iban_valid(s) is ok


@pytest.mark.parametrize("s,ok", [("27AAPFU0939F1ZV", True), ("27AAPFU0939F1ZW", False)])
def test_gstin(s: str, ok: bool) -> None:
    assert v.gstin_valid(s) is ok


@pytest.mark.parametrize("s,ok", [("ABCPE1234F", True), ("ABCXE1234F", False), ("ABCDE12345", False)])
def test_pan(s: str, ok: bool) -> None:
    assert v.pan_valid(s) is ok


@pytest.mark.parametrize("s,ok", [("123-45-6789", True), ("000-12-3456", False), ("666-12-3456", False), ("912-12-3456", False), ("123-00-4567", False), ("123-45-0000", False)])
def test_ssn(s: str, ok: bool) -> None:
    assert v.ssn_valid(s) is ok


def test_entropy() -> None:
    assert v.entropy("aaaaaaaaaaaaaaaa") < 1
    assert v.entropy("q8ZtK2mV9xLp4RwN7cYb") > 4
