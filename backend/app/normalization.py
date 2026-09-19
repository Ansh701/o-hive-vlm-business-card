from __future__ import annotations

import re

import phonenumbers
from email_validator import EmailNotValidError, validate_email

PHONE_CHARACTERS = re.compile(r"^[\d\s()+.\-/xXextEXT]+$")


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def normalize_email(value: str | None) -> tuple[str | None, list[str]]:
    normalized = normalize_text(value)
    if normalized is None:
        return None, []
    try:
        result = validate_email(normalized, check_deliverability=False)
    except EmailNotValidError:
        return normalized, ["Email format needs review"]
    local, _, domain = result.normalized.partition("@")
    return f"{local}@{domain.lower()}", []


def normalize_phone(value: str | None) -> tuple[str | None, list[str]]:
    normalized = normalize_text(value)
    if normalized is None:
        return None, []
    if not PHONE_CHARACTERS.fullmatch(normalized):
        return normalized, ["Phone format needs review"]

    if not normalized.startswith("+"):
        digit_count = sum(character.isdigit() for character in normalized)
        if digit_count >= 7:
            return normalized, ["Phone country is ambiguous; original formatting preserved"]
        return normalized, ["Phone format needs review"]

    try:
        number = phonenumbers.parse(normalized, None)
    except phonenumbers.NumberParseException:
        return normalized, ["Phone format needs review"]
    if not phonenumbers.is_possible_number(number):
        return normalized, ["Phone format needs review"]
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164), []

