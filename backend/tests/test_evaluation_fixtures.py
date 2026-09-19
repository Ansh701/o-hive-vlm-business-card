from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from scripts.evaluate_extraction import OFFICIAL_FIELDS, score_dataset
from scripts.generate_synthetic_cards import VARIANTS, generate_cards

EXPECTED_VARIANTS = {
    "clean-horizontal",
    "vertical",
    "low-contrast",
    "with-logo",
    "phone-format",
    "missing-email",
    "missing-location",
    "complex-name",
    "slightly-rotated",
}


def test_generator_creates_all_named_permission_safe_cards(tmp_path: Path) -> None:
    manifest = generate_cards(tmp_path)

    assert set(VARIANTS) == EXPECTED_VARIANTS
    assert set(manifest) == EXPECTED_VARIANTS
    for name, record in manifest.items():
        image_path = tmp_path / record["filename"]
        assert image_path.is_file(), name
        with Image.open(image_path) as image:
            image.verify()
        assert set(record["expected"]) == set(OFFICIAL_FIELDS)
        assert record["synthetic"] is True


def test_ground_truth_contains_literal_expected_fields_only() -> None:
    path = Path("evaluation/ground-truth.json")
    records = json.loads(path.read_text(encoding="utf-8"))

    assert set(records) == EXPECTED_VARIANTS
    assert records["clean-horizontal"]["expected"] == {
        "first_name": "Mina",
        "last_name": "Patel",
        "job_title": "Product Designer",
        "company": "Northstar Studio",
        "location": "Bengaluru, India",
        "phone_number": "+91 98765 43210",
        "email": "mina@northstar.example",
    }
    assert records["missing-email"]["expected"]["email"] is None
    assert records["missing-location"]["expected"]["location"] is None
    assert records["complex-name"]["expected"]["first_name"] == "María José"
    assert records["complex-name"]["expected"]["last_name"] == "Carreño Quiñones"
    assert all(
        value is None or ".example" in value
        for record in records.values()
        for field, value in record["expected"].items()
        if field == "email"
    )


def test_field_scorer_reports_correct_partial_and_failed_without_raw_values() -> None:
    expected: dict[str, dict[str, Any]] = {
        "card": {
            "expected": {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "job_title": None,
                "company": "Difference Works",
                "location": "London",
                "phone_number": "+44 20 7946 0000",
                "email": "ada@example.com",
            }
        }
    }
    predictions = {
        "card": {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "job_title": None,
            "company": "Difference Work",
            "location": None,
            "phone_number": "+44 20 7946 0000",
            "email": "ADA@example.com",
            "unexpected_model_text": "must never be copied to report",
        }
    }

    report = score_dataset(expected, predictions)

    assert report["cards_tested"] == 1
    assert report["fields_expected"] == 7
    assert report["correct_fields"] == 5
    assert report["partial_fields"] == 1
    assert report["failed_fields"] == 1
    assert report["accuracy"] == 5 / 7
    serialized = json.dumps(report)
    assert "unexpected_model_text" not in serialized
    assert "Difference Work" not in serialized
