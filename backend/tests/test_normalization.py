from __future__ import annotations

import pytest

from backend.app.normalization import normalize_email, normalize_phone, normalize_text


def test_email_trims_and_lowercases_only_domain() -> None:
    value, warnings = normalize_email("  Ada.Lovelace@EXAMPLE.COM  ")

    assert value == "Ada.Lovelace@example.com"
    assert warnings == []


def test_invalid_email_is_preserved_for_review_not_repaired() -> None:
    value, warnings = normalize_email("ada at example dot com")

    assert value == "ada at example dot com"
    assert warnings == ["Email format needs review"]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_email_stays_null(value: str | None) -> None:
    assert normalize_email(value) == (None, [])


@pytest.mark.parametrize(
    "source",
    ["+1 (332) 241-6313", "+1-332-241-6313", "+1 332 241 6313"],
)
def test_explicit_international_phone_normalizes_to_e164(source: str) -> None:
    assert normalize_phone(source) == ("+13322416313", [])


def test_phone_without_country_is_preserved_without_guessing() -> None:
    assert normalize_phone("(332) 241 6313") == (
        "(332) 241 6313",
        ["Phone country is ambiguous; original formatting preserved"],
    )


def test_invalid_phone_is_preserved_for_manual_correction() -> None:
    assert normalize_phone("Call the office") == (
        "Call the office",
        ["Phone format needs review"],
    )


def test_text_normalization_collapses_whitespace_without_inference() -> None:
    assert normalize_text("  Senior   Researcher \n AI Lab ") == "Senior Researcher AI Lab"
    assert normalize_text("   ") is None
    assert normalize_text(None) is None

