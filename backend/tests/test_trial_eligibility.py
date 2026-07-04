"""Tests for deterministic trial eligibility from a verified email address."""

from dataclasses import FrozenInstanceError

import pytest

import backend.trial.eligibility as eligibility
from backend.trial.eligibility import EligibilityDecision, classify_verified_email


PERSONAL_DOMAINS = [
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
]


@pytest.mark.parametrize(
    "domain",
    PERSONAL_DOMAINS,
)
def test_personal_email_domains_receive_200_pages(domain: str) -> None:
    decision = classify_verified_email(f"person@{domain}")

    assert decision == EligibilityDecision(
        normalized_email=f"person@{domain}",
        normalized_domain=domain,
        granted_pages=200,
    )


@pytest.mark.parametrize(
    "email",
    [
        "student@university.edu",
        "researcher@lab.university.edu",
        "member@nonprofit.org",
        "member@chapter.nonprofit.org",
        "employee@acme.com",
    ],
)
def test_institutional_and_non_personal_domains_receive_400_pages(
    email: str,
) -> None:
    assert classify_verified_email(email).granted_pages == 400


def test_email_and_domain_are_lowercase_and_whitespace_normalized() -> None:
    decision = classify_verified_email("  Person.Name@GMAIL.COM  ")

    assert decision.normalized_email == "person.name@gmail.com"
    assert decision.normalized_domain == "gmail.com"
    assert decision.granted_pages == 200


def test_personal_domain_matching_is_exact() -> None:
    assert classify_verified_email("person@gmail.com.acme.com").granted_pages == 400
    assert classify_verified_email("person@notgmail.com").granted_pages == 400


def test_unicode_and_alabel_domains_have_the_same_canonical_decision() -> None:
    unicode_decision = classify_verified_email("person@bücher.example")
    alabel_decision = classify_verified_email("person@xn--bcher-kva.example")

    assert unicode_decision == alabel_decision
    assert unicode_decision.normalized_domain == "xn--bcher-kva.example"
    assert unicode_decision.normalized_email == "person@xn--bcher-kva.example"
    assert unicode_decision.granted_pages == 400


def test_unicode_local_part_is_rejected_before_case_normalization() -> None:
    with pytest.raises(ValueError, match="valid email"):
        classify_verified_email("K@example.com")


def test_invalid_idna_domain_is_rejected() -> None:
    with pytest.raises(ValueError, match="valid email"):
        classify_verified_email("person@\ud800.example")


def test_decision_is_frozen_and_has_stable_rule_version() -> None:
    decision = classify_verified_email("person@acme.com")

    assert decision.rule_version == "2026-07-04"
    with pytest.raises(FrozenInstanceError):
        decision.granted_pages = 200


def test_version_and_personal_domains_share_one_immutable_ruleset() -> None:
    assert eligibility.ELIGIBILITY_RULES.version == "2026-07-04"
    assert eligibility.ELIGIBILITY_RULES.personal_domains == frozenset(
        PERSONAL_DOMAINS
    )
    with pytest.raises(FrozenInstanceError):
        eligibility.ELIGIBILITY_RULES.version = "changed"


def test_canonical_mailbox_accepts_254_ascii_characters() -> None:
    local_part = "a" * 64
    domain = ".".join(["b" * 63, "c" * 63, "d" * 61])
    email = f"{local_part}@{domain}"

    assert len(email) == 254
    assert classify_verified_email(email).normalized_email == email


def test_canonical_mailbox_rejects_255_ascii_characters() -> None:
    local_part = "a" * 64
    domain = ".".join(["b" * 63, "c" * 63, "d" * 62])
    email = f"{local_part}@{domain}"

    assert len(email) == 255
    with pytest.raises(ValueError, match="valid email"):
        classify_verified_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "",
        "   ",
        "missing-at.example.com",
        "two@@example.com",
        "@example.com",
        "person@",
        "person@example",
        "person@example..com",
        "person@-example.com",
        "person@example-.com",
        "person@exam ple.com",
        "person@example_com",
        ".person@example.com",
        "person.@example.com",
        "person..name@example.com",
        "person name@example.com",
    ],
)
def test_malformed_email_is_rejected(email: str) -> None:
    with pytest.raises(ValueError, match="valid email"):
        classify_verified_email(email)


@pytest.mark.parametrize("email", [None, 42, object()])
def test_unsupported_email_input_is_rejected(email: object) -> None:
    with pytest.raises(ValueError, match="valid email"):
        classify_verified_email(email)  # type: ignore[arg-type]
