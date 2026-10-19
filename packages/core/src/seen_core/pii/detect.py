"""Tier-1 PII and secret detection (plan 11B). Stdlib regex plus validators, safe for hooks.

Findings carry type, confidence, counts and keyed fingerprints. Never the value.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import re
import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .. import secret
from . import validators as v

CONF_RANK = {"low": 0, "medium": 1, "high": 2}
DOC_DOMAINS = {"example.com", "example.org", "example.net", "localhost"}
TEST_CARDS = {"4111111111111111", "4242424242424242", "4012888888881881", "5555555555554444", "5105105105105100",
              "378282246310005", "371449635398431", "6011111111111117", "3530111333300000", "4000056655665556"}
UPI_HANDLES = {"okaxis", "oksbi", "okhdfcbank", "okicici", "ybl", "ibl", "axl", "paytm", "upi", "apl", "yapl", "fbl", "ikwik",
               "freecharge", "jupiteraxis", "axisbank", "sbi", "hdfcbank", "icici", "kotak", "barodampay", "pnb", "aubank"}
PHONE_CTX = re.compile(r"(?i)\b(phone|mobile|mob|tel|cell|contact|whatsapp|call|ph)\b")
AADHAAR_CTX = re.compile(r"(?i)\b(aadhaa?r|uid|uidai|आधार)\b")
VID_CTX = re.compile(r"(?i)\b(vid|virtual id|aadhaa?r|uid|uidai)\b")
DOB_CTX = re.compile(r"(?i)\b(dob|d\.o\.b|date of birth|birth ?date|born)\b")

_RX = {
    "email": re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]{1,64}@((?:[A-Za-z0-9-]{1,63}\.){1,8}[A-Za-z]{2,24})\b"),
    "aadhaar": re.compile(r"(?<![\w-])[2-9]\d{3}([ -]?)\d{4}\1\d{4}(?![\w-])"),  # 4-4-4, one consistent separator
    "vid": re.compile(r"(?<![\w-])[2-9]\d{3}([ -]?)\d{4}\1\d{4}\1\d{4}(?![\w-])"),  # 16-digit Aadhaar Virtual ID
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "card": re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b"),
    "ssn": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "upi": re.compile(r"(?<![\w.-])[A-Za-z0-9._-]{2,64}@([A-Za-z]{2,20})(?![\w.@-])"),
    "phone": re.compile(r"(?<![\w+])(?:\+91[ -]?|91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)|\+[1-9]\d{0,2}[ -]?\d{2,4}[ -]?\d{3,4}[ -]?\d{3,4}(?!\d)"),
    "dob": re.compile(r"(?<!\d)(?:\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}|\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (?:19|20)\d{2})(?!\d)"),
    "passport": re.compile(r"\b[A-PR-WY][1-9]\d{6}\b"),
    "gstin": re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"),
    "voter_id": re.compile(r"\b[A-Z]{3}\d{7}\b"),
    "driving_licence": re.compile(r"\b[A-Z]{2}[- ]?\d{2}[- ]?(?:19|20)\d{2}[- ]?\d{7}\b"),
}
_SECRETS = [
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "aws_key", "high"),
    (re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"), "private_key", "high"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "jwt", "high"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b"), "github_token", "high"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "slack_token", "high"),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b"), "api_key", "high"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "google_api_key", "high"),
    (re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b"), "stripe_key", "high"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "gitlab_token", "high"),
]
_BEARER = re.compile(r"(?i)\bbearer[ \t]+([A-Za-z0-9._~+/=-]{20,})")
# scheme://user:password@host: the password is the secret
_URL_CRED = re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://([^\s:/@'\"]{1,64}:([^\s@/'\"]{3,128})@[\w.-]+)")
_PLACEHOLDER = re.compile(r"(?i)^(?:password|passwd|pass|secret|changeme|xxx+|\*+|your[-_]?\w*|\$\{?\w.*|<.*>|\{.*\}|%\w+%)$")
# a public IPv4 is personal data (DPDP); well-known resolvers are infrastructure, not a person
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)")
_WELL_KNOWN_IPS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "208.67.222.222", "208.67.220.220"}
# bounded on purpose: unbounded runs around the keyword backtrack polynomially (ReDoS) on "key.key.key..."
_ASSIGN = re.compile(r"(?i)(?<![\w.-])['\"]?[\w.-]{0,40}?(?:key|secret|token|passwd|password|pwd|credential)[\w-]{0,20}['\"]?[ \t]{0,4}[:=][ \t]{0,4}['\"]?([A-Za-z0-9/+_=.$!#@%^&*~-]{12,256})")
CTX_WINDOW = 32
CUSTOM_RULE_SECONDS = 0.25


@dataclass
class Finding:
    type: str
    confidence: str
    count: int = 0
    distinct: int = 0
    detector: str = "regex"
    fingerprints: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)  # in-memory only, for redaction; never stored


def _norm(typ: str, value: str) -> str:
    if typ == "email" or typ == "upi":
        return value.lower()
    return re.sub(r"[\s-]", "", value).upper()


def _near(rx: re.Pattern[str], text: str, start: int, end: int) -> bool:
    return bool(rx.search(text[max(0, start - CTX_WINDOW): end + 8]))


def _hits(text: str) -> list[tuple[str, str, int, int, str, str]]:
    """(type, confidence, start, end, value, detector)"""
    out: list[tuple[str, str, int, int, str, str]] = []
    for m in _RX["email"].finditer(text):
        if m.group(1).lower() not in DOC_DOMAINS:
            out.append(("email", "medium", m.start(), m.end(), m.group(0), "regex"))
    for m in _RX["aadhaar"].finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) == 12 and v.verhoeff_valid(d):
            # 1 in 10 random 12-digit numbers pass Verhoeff: grouping or a keyword is what makes it high
            conf = "high" if m.group(1) or _near(AADHAAR_CTX, text, m.start(), m.end()) else "medium"
            out.append(("aadhaar", conf, m.start(), m.end(), d, "regex+verhoeff"))
    for m in _RX["vid"].finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        # 1 in 10 random 16-digit numbers pass Verhoeff, and cards are 16 digits: only with a keyword nearby
        if v.verhoeff_valid(d) and _near(VID_CTX, text, m.start(), m.end()):
            out.append(("aadhaar", "high", m.start(), m.end(), d, "regex+verhoeff:vid"))
    for m in _RX["pan"].finditer(text):
        if v.pan_valid(m.group(0)):
            out.append(("pan", "medium", m.start(), m.end(), m.group(0), "regex"))
    for m in _RX["card"].finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if 13 <= len(d) <= 19 and d not in TEST_CARDS and _issuer(d) and v.luhn_valid(d):
            out.append(("card", "high", m.start(), m.end(), d, "regex+luhn"))
    for m in _RX["iban"].finditer(text):
        if v.iban_valid(m.group(0)):
            out.append(("iban", "high", m.start(), m.end(), m.group(0), "regex+mod97"))
    for m in _RX["ssn"].finditer(text):
        if v.ssn_valid(m.group(0)):
            out.append(("ssn", "medium", m.start(), m.end(), m.group(0), "regex"))
    for m in _RX["upi"].finditer(text):
        if m.group(1).lower() in UPI_HANDLES:
            out.append(("upi", "medium", m.start(), m.end(), m.group(0), "regex"))
    for m in _RX["phone"].finditer(text):
        conf = "medium" if _near(PHONE_CTX, text, m.start(), m.end()) or m.group(0).startswith("+") else "low"
        out.append(("phone", conf, m.start(), m.end(), m.group(0), "regex"))
    for m in _RX["dob"].finditer(text):
        if _near(DOB_CTX, text, m.start(), m.end()):
            out.append(("dob", "medium", m.start(), m.end(), m.group(0), "regex+context"))
    for typ, ctx in (("passport", r"(?i)passport"), ("voter_id", r"(?i)\b(voter|epic)\b"), ("driving_licence", r"(?i)\b(licen[cs]e|dl)\b")):
        crx = re.compile(ctx)
        for m in _RX[typ].finditer(text):
            out.append((typ, "medium" if _near(crx, text, m.start(), m.end()) else "low", m.start(), m.end(), m.group(0), "regex"))
    for m in _RX["gstin"].finditer(text):
        if v.gstin_valid(m.group(0)):
            out.append(("gstin", "medium", m.start(), m.end(), m.group(0), "regex+checksum"))
    for rx, name, conf in _SECRETS:
        for m in rx.finditer(text):
            out.append(("secret", conf, m.start(), m.end(), m.group(0), f"secret:{name}"))
    for m in _ASSIGN.finditer(text):
        val = m.group(1)
        if not val.isdigit() and _secret_like(val):
            out.append(("secret", "medium", m.start(1), m.end(1), val, "secret:entropy"))
    for m in _BEARER.finditer(text):
        if v.entropy(m.group(1)) >= 3.5:
            out.append(("secret", "medium", m.start(1), m.end(1), m.group(1), "secret:bearer"))
    for m in _URL_CRED.finditer(text):
        if not _PLACEHOLDER.match(m.group(2)):  # span is user:password@host so it outranks the email detector on the same text
            out.append(("secret", "medium", m.start(1), m.end(1), m.group(2), "secret:url_credential"))
    for m in _IPV4.finditer(text):
        try:
            ip = ipaddress.IPv4Address(m.group(0))
        except ValueError:
            continue
        if ip.is_global and m.group(0) not in _WELL_KNOWN_IPS:
            out.append(("ip", "medium", m.start(), m.end(), m.group(0), "regex+ipaddress"))
    return out


def _secret_like(val: str) -> bool:
    if len(val) >= 16:
        return v.entropy(val) >= 3.5
    classes = sum(bool(re.search(p, val)) for p in ("[a-z]", "[A-Z]", "[0-9]", r"[^A-Za-z0-9]"))
    return classes >= 3 and v.entropy(val) >= 3.2  # short values: need several character classes to beat "changeme"


def _issuer(d: str) -> bool:
    two, three, four = int(d[:2]), int(d[:3]), int(d[:4])
    return (d[0] == "4" or 51 <= two <= 55 or 2221 <= four <= 2720 or two in (34, 37) or d.startswith(("6011", "65", "60", "81", "82", "508"))
            or two in (36, 38) or 300 <= three <= 305 or two == 35)


FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com", "msn.com",
             "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "rediffmail.com", "zoho.com", "yandex.com", "gmx.com", "mail.com"}
PUBLIC_SUFFIXES = {"co.in", "org.in", "net.in", "ac.in", "gov.in", "edu.in", "co.uk", "org.uk", "com.au", "co.jp", "com.br", "com.sg"}


def usable_patterns(patterns: list[str]) -> list[str]:
    """A repo-controlled allowlist must not switch detection off. Accepted: an exact value, or
    '*@<domain>' for a real domain (two or more labels, not free-mail, not a bare public suffix)."""
    out = []
    for p in patterns:
        if p.startswith("*"):
            dom = p[2:].lower() if p.startswith("*@") else ""
            labels = dom.split(".")
            if (not dom or any(ch in dom for ch in "*?[]@") or len(labels) < 2 or not all(labels)
                    or dom in FREE_MAIL or dom in PUBLIC_SUFFIXES or len(dom.replace(".", "")) < 4):
                continue
        elif any(ch in p for ch in "*?[]") or len(re.sub(r"[.@-]", "", p)) < 4:
            continue
        out.append(p)
    return out


def _allowed(typ: str, value: str, patterns: list[str]) -> bool:
    if typ == "secret":
        return False  # never allowlist credentials
    lv = value.lower()
    return any(fnmatch.fnmatch(lv, p.lower()) for p in patterns)


@contextmanager
def _deadline(seconds: float) -> Iterator[None]:
    """Cut a regex that backtracks: sre polls signals, so SIGALRM interrupts it. Main thread only (every hook run);
    elsewhere (API worker threads) the static check in projectcfg.safe_pattern is the only guard."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def fire(_s: int, _f: object) -> None:
        raise TimeoutError

    old = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def scan(text: str, *, only: list[str] | None = None, allow_values: list[str] | None = None,
         custom_rules: list[dict[str, Any]] | None = None, min_confidence: str = "low") -> list[Finding]:
    return scan_with_stats(text, only=only, allow_values=allow_values, custom_rules=custom_rules, min_confidence=min_confidence)[0]


def scan_with_stats(text: str, *, only: list[str] | None = None, allow_values: list[str] | None = None,
                    custom_rules: list[dict[str, Any]] | None = None, min_confidence: str = "low") -> tuple[list[Finding], int]:
    """Findings plus how many values the allowlist suppressed (reported, so allowlisting is visible)."""
    allow = usable_patterns(allow_values or [])
    allowed = 0
    hits = _hits(text)
    for r in custom_rules or []:
        try:
            rx = re.compile(str(r["pattern"]))
        except (re.error, KeyError):
            continue
        conf = r.get("confidence") if r.get("confidence") in CONF_RANK else "medium"
        try:
            with _deadline(CUSTOM_RULE_SECONDS):
                hits += [("custom", str(conf), m.start(), m.end(), m.group(0), f"custom:{r.get('id', 'rule')}") for m in rx.finditer(text)]
        except TimeoutError:
            continue  # a rule that cannot finish in time is skipped for this text, never allowed to hang the prompt
    # the same span is one identifier: keep the highest-confidence, most specific claim on it
    hits.sort(key=lambda h: (-(h[3] - h[2]), -CONF_RANK[h[1]], h[0] == "phone", h[2]))  # longest claim on a span wins
    taken: list[tuple[int, int]] = []
    found: dict[tuple[str, str, str], Finding] = {}
    seen: dict[tuple[str, str, str], set[str]] = {}
    for typ, conf, s, e, val, det in hits:
        if only and typ not in only:
            continue
        if CONF_RANK[conf] < CONF_RANK[min_confidence]:
            continue
        if _allowed(typ, val, allow):
            allowed += 1
            continue
        if any(s < te and ts < e for ts, te in taken):
            continue
        taken.append((s, e))
        key = (typ, conf, det if typ in ("custom", "secret") else "regex")
        f = found.setdefault(key, Finding(type=typ, confidence=conf, detector=det))
        f.count += 1
        f.spans.append((s, e))
        fp = secret.keyed(_norm(typ, val), 16)
        seen.setdefault(key, set())
        if fp not in seen[key]:
            seen[key].add(fp)
            f.fingerprints.append(fp)
        f.distinct = len(seen[key])
    return sorted(found.values(), key=lambda f: (-CONF_RANK[f.confidence], f.type)), allowed
