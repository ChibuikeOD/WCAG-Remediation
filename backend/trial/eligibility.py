"""Deterministic page eligibility for verified trial email addresses."""

from dataclasses import dataclass
import re


_PERSONAL_DOMAINS = frozenset(
    {
        "gmail.com",
        "outlook.com",
        "hotmail.com",
        "yahoo.com",
        "icloud.com",
    }
)
_LOCAL_PART_PATTERN = re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+")
_DOMAIN_LABEL_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
_INVALID_EMAIL_MESSAGE = "A valid email address is required"


@dataclass(frozen=True)
class EligibilityDecision:
    """A stable eligibility result derived solely from a normalized email."""

    normalized_email: str
    normalized_domain: str
    granted_pages: int
    rule_version: str = "2026-07-04"


def classify_verified_email(email: str) -> EligibilityDecision:
    """Classify a verified email into the deterministic trial page allowance."""
    if not isinstance(email, str):
        raise ValueError(_INVALID_EMAIL_MESSAGE)

    normalized_email = email.strip().lower()
    if normalized_email.count("@") != 1:
        raise ValueError(_INVALID_EMAIL_MESSAGE)

    local_part, domain = normalized_email.split("@")
    if not _valid_local_part(local_part) or not _valid_domain(domain):
        raise ValueError(_INVALID_EMAIL_MESSAGE)

    granted_pages = 200 if domain in _PERSONAL_DOMAINS else 400
    return EligibilityDecision(
        normalized_email=normalized_email,
        normalized_domain=domain,
        granted_pages=granted_pages,
    )


def _valid_local_part(local_part: str) -> bool:
    return (
        0 < len(local_part) <= 64
        and not local_part.startswith(".")
        and not local_part.endswith(".")
        and ".." not in local_part
        and _LOCAL_PART_PATTERN.fullmatch(local_part) is not None
    )


def _valid_domain(domain: str) -> bool:
    if not domain or len(domain) > 253 or "." not in domain or ".." in domain:
        return False
    return all(
        _DOMAIN_LABEL_PATTERN.fullmatch(label) is not None
        for label in domain.split(".")
    )
