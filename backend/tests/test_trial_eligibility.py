"""Tests for deterministic trial eligibility from a verified email address."""

from dataclasses import FrozenInstanceError

import pytest

from backend.trial.eligibility import EligibilityDecision, classify_verified_email


@pytest.mark.parametrize(
    "domain",
    ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"],
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


def test_decision_is_frozen_and_has_stable_rule_version() -> None:
    decision = classify_verified_email("person@acme.com")

    assert decision.rule_version == "2026-07-04"
    with pytest.raises(FrozenInstanceError):
        decision.granted_pages = 200


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
