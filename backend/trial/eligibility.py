"""Deterministic page eligibility for verified trial email addresses."""

from dataclasses import dataclass
import re


_LOCAL_PART_PATTERN = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+")
_DOMAIN_LABEL_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
_INVALID_EMAIL_MESSAGE = "A valid email address is required"


@dataclass(frozen=True)
class EligibilityRules:
    """The versioned inputs to deterministic eligibility classification."""

    version: str
    personal_domains: frozenset[str]


ELIGIBILITY_RULES = EligibilityRules(
    version="2026-07-04",
    personal_domains=frozenset(
        {
            "gmail.com",
            "googlemail.com",
            "outlook.com",
            "hotmail.com",
            "live.com",
            "msn.com",
            "yahoo.com",
            "icloud.com",
            "me.com",
            "mac.com",
        }
    ),
)


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

    stripped_email = email.strip()
    if stripped_email.count("@") != 1:
        raise ValueError(_INVALID_EMAIL_MESSAGE)

    original_local_part, original_domain = stripped_email.split("@")
    if not _valid_local_part(original_local_part):
        raise ValueError(_INVALID_EMAIL_MESSAGE)

    domain = _canonicalize_domain(original_domain)
    if domain is None:
        raise ValueError(_INVALID_EMAIL_MESSAGE)

    local_part = original_local_part.lower()
    normalized_email = f"{local_part}@{domain}"
    if len(normalized_email.encode("ascii")) > 254:
        raise ValueError(_INVALID_EMAIL_MESSAGE)

    granted_pages = (
        200 if domain in ELIGIBILITY_RULES.personal_domains else 400
    )
    return EligibilityDecision(
        normalized_email=normalized_email,
        normalized_domain=domain,
        granted_pages=granted_pages,
        rule_version=ELIGIBILITY_RULES.version,
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


def _canonicalize_domain(domain: str) -> str | None:
    if not domain:
        return None
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
        unicode_domain = ascii_domain.encode("ascii").decode("idna")
        round_trip = unicode_domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if round_trip != ascii_domain or not _valid_domain(ascii_domain):
        return None
    return ascii_domain
