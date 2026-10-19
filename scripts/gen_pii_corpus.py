"""Generate the labelled PII corpus (synthetic values only). Deterministic: re-running gives the same file.

Every positive is fabricated: checksum-valid Aadhaar, Luhn-valid cards on real issuer prefixes but random
account digits, mod-97-valid IBANs, and so on. Hard negatives look like PII and must not be flagged.
"""

import json
import random
import string
from pathlib import Path

from seen_core.pii import validators as v

R = random.Random(20261018)
OUT = Path(__file__).resolve().parents[1] / "tests/fixtures/pii_corpus/corpus.jsonl"
FIRST = ["Asha", "Ravi", "Meera", "Arjun", "Priya", "Kiran", "John", "Maria", "Chen", "Fatima"]
DOMAINS = ["corp.test.in", "mail.invalid", "hospital.test", "bank.test", "demo-co.test"]


def digits(n: int) -> str:
    return "".join(R.choice(string.digits) for _ in range(n))


def aadhaar() -> str:
    base = R.choice("23456789") + digits(10)
    d = base + v.verhoeff_digit(base)
    return R.choice([d, f"{d[:4]} {d[4:8]} {d[8:]}", f"{d[:4]}-{d[4:8]}-{d[8:]}"])


def luhn(prefix: str, length: int) -> str:
    base = prefix + digits(length - len(prefix) - 1)
    return next(base + str(c) for c in range(10) if v.luhn_valid(base + str(c)))


def card() -> str:
    d = luhn(*R.choice([("4", 16), ("53", 16), ("2221", 16), ("37", 15), ("6011", 16), ("60", 16), ("508", 16), ("35", 16)]))
    return R.choice([d, " ".join(d[i:i + 4] for i in range(0, len(d), 4))])


def iban() -> str:
    cc, bban = R.choice([("GB", "WEST" + digits(14)), ("DE", digits(18)), ("FR", digits(10) + "ABCDE" + digits(8)), ("AE", digits(19))])
    for ck in range(100):
        s = f"{cc}{ck:02d}{bban}"
        if v.iban_valid(s):
            return s
    raise AssertionError


def pan() -> str:
    return "".join(R.choices(string.ascii_uppercase, k=3)) + R.choice("PCHFATBLJG") + R.choice(string.ascii_uppercase) + digits(4) + R.choice(string.ascii_uppercase)


def gstin() -> str:
    while True:
        s = f"{R.randint(1, 37):02d}{pan()}{R.choice('123456789')}Z"
        for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if v.gstin_valid(s + c):
                return s + c


def ssn() -> str:
    return f"{R.randint(1, 665):03d}-{R.randint(1, 99):02d}-{R.randint(1, 9999):04d}"


def secret_token() -> str:
    return R.choice([
        "AKIA" + "".join(R.choices(string.ascii_uppercase + string.digits, k=16)),
        "ghp_" + "".join(R.choices(string.ascii_letters + string.digits, k=36)),
        "-----BEGIN RSA PRIVATE KEY-----",
        "eyJ" + "".join(R.choices(string.ascii_letters, k=12)) + ".eyJ" + "".join(R.choices(string.ascii_letters, k=16)) + "." + "".join(R.choices(string.ascii_letters + "_-", k=20)),
        "api_key = '" + "".join(R.choices(string.ascii_letters + string.digits, k=24)) + "'",
    ])


POS = {
    "aadhaar": [lambda: f"Aadhaar: {aadhaar()}", lambda: f"UID {aadhaar()} verified for {R.choice(FIRST)}", lambda: f"row,{aadhaar()},active"],
    "card": [lambda: f"card {card()} exp 09/29", lambda: f"charged {card()} for INR 450", lambda: f"PAN-card-free: {card()}"],
    "iban": [lambda: f"IBAN {iban()}", lambda: f"wire to {iban()} today"],
    "secret": [lambda: secret_token(), lambda: f"export TOKEN={secret_token()}"],
    "email": [lambda: f"{R.choice(FIRST).lower()}.{digits(2)}@{R.choice(DOMAINS)}", lambda: f"cc: {R.choice(FIRST)} <{R.choice(FIRST).lower()}@{R.choice(DOMAINS)}>"],
    "pan": [lambda: f"PAN {pan()}", lambda: f"tax id {pan()} on invoice"],
    "phone": [lambda: f"mobile {R.choice('6789')}{digits(4)} {digits(5)}", lambda: f"call +91 {R.choice('6789')}{digits(4)}{digits(5)}", lambda: f"tel +44 20 {digits(4)} {digits(4)}"],
    "ssn": [lambda: f"SSN {ssn()}"],
    "upi": [lambda: f"pay {R.choice(FIRST).lower()}{digits(2)}@{R.choice(['okaxis', 'ybl', 'paytm', 'oksbi'])}"],
    "dob": [lambda: f"DOB: {R.randint(1, 28):02d}/{R.randint(1, 12):02d}/{R.randint(1950, 2005)}", lambda: f"date of birth {R.randint(1950, 2005)}-0{R.randint(1, 9)}-1{R.randint(0, 9)}"],
    "gstin": [lambda: f"GSTIN {gstin()}"],
    "passport": [lambda: f"passport no {R.choice('ABCDEFGHJKLMNPRSTUVWY')}{R.randint(1, 9)}{digits(5)}{R.randint(1, 9)}"],
}
NEG = [
    lambda: f"order {digits(8)} {digits(4)} shipped",
    lambda: f"invoice INV-{digits(12)}",
    lambda: "Visa test card 4111 1111 1111 1111",
    lambda: "Stripe test 4242424242424242",
    lambda: f"uuid {''.join(R.choices('0123456789abcdef', k=8))}-{''.join(R.choices('0123456789abcdef', k=4))}-4{''.join(R.choices('0123456789abcdef', k=3))}-a{''.join(R.choices('0123456789abcdef', k=3))}-{digits(12)}",
    lambda: f"commit {''.join(R.choices('0123456789abcdef', k=40))}",
    lambda: f"version {R.randint(1, 9)}.{R.randint(0, 20)}.{R.randint(0, 99)} released 2026-10-{R.randint(10, 28)}",
    lambda: f"see docs at user{digits(2)}@example.com",
    lambda: f"listening on port {R.randint(1024, 65535)} pid {digits(5)}",
    lambda: f"ticket ABCDE{digits(5)}",
    lambda: f"sha256 {''.join(R.choices('0123456789abcdef', k=64))}",
    lambda: f"timestamp {digits(13)}",
    lambda: "password = 'aaaaaaaaaaaaaaaaaaaa'",
    lambda: f"coords {R.randint(1, 99)}.{digits(6)}, {R.randint(1, 99)}.{digits(6)}",
    lambda: f"npm i left-pad@{R.randint(1, 9)}.{R.randint(0, 9)}.{R.randint(0, 9)}",
]


def ip() -> str:
    return f"{R.choice([13, 18, 34, 52, 54, 99, 104, 151, 185])}.{R.randint(1, 254)}.{R.randint(1, 254)}.{R.randint(1, 254)}"


# added after the shuffle so the rows above stay byte-identical (2026-10-19 recall work)
EXTRA_NEG = ["service at 10.2.3.4 healthy", "service at 192.168.0.17 healthy", "service at 127.0.0.1 healthy",
             "service at 172.16.8.9 healthy", "service at 8.8.8.8 healthy", "service at 192.0.2.55 healthy",
             "password: changeme", "postgres://user:password@localhost/db", "token_count: 1234567890123456"]


def extra() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [{"text": f"login from {ip()} rejected", "labels": ["ip"]} for _ in range(20)]
    for _ in range(10):
        tok = "".join(R.choice(string.ascii_letters + string.digits) for _ in range(24))
        text = R.choice([f'{{"api_key": "{tok}"}}', f"Authorization: Bearer {tok}", f"postgres://svc:{tok[:12]}@db.corp.test:5432/app"])
        rows.append({"text": text, "labels": ["secret"]})
    return rows + [{"text": t, "labels": []} for t in EXTRA_NEG]


def main() -> None:
    rows = []
    for typ, gens in POS.items():
        for _ in range(60):
            rows.append({"text": R.choice(gens)(), "labels": [typ]})
    for _ in range(400):
        rows.append({"text": R.choice(NEG)(), "labels": []})
    R.shuffle(rows)
    rows += extra()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"wrote {len(rows)} samples to {OUT}")


if __name__ == "__main__":
    main()
