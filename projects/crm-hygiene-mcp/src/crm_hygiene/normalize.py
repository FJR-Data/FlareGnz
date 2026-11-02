"""Normalization helpers shared by audits and reconciliation.

CRM exports disagree on case, accents, legal suffixes and URL formats. Every
comparison in this package goes through these functions so that "Acme Ltda."
and "ACME" are treated as the same company, while real value changes are not
hidden.
"""

from __future__ import annotations

import re
import unicodedata

# Legal-entity suffixes common in Brazilian and US CRM data.
LEGAL_SUFFIXES = {
    "ltda", "sa", "s/a", "me", "epp", "eireli", "inc", "llc", "corp", "co", "ltd", "plc", "gmbh",
}

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_NON_WORD = re.compile(r"[^a-z0-9/ ]+")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm_text(value: str | None) -> str:
    """Trim, lowercase, remove accents and collapse whitespace."""
    if value is None:
        return ""
    return _SPACES.sub(" ", strip_accents(str(value)).lower()).strip()


def norm_company(name: str | None) -> str:
    """Canonical company name: no accents, punctuation or legal suffixes."""
    text = norm_text(name).replace(".", "")
    text = _NON_WORD.sub(" ", text)
    tokens = [t for t in text.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)


def norm_domain(value: str | None) -> str:
    """Extract a bare domain from a website URL or an e-mail address."""
    text = norm_text(value)
    if not text:
        return ""
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0]
    if text.startswith("www."):
        text = text[4:]
    return text


def is_valid_email(value: str | None) -> bool:
    return bool(value) and bool(_EMAIL_RE.match(str(value).strip()))


def is_blank(value: str | None) -> bool:
    return value is None or str(value).strip() == ""
