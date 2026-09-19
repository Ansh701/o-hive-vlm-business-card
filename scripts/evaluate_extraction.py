from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

OFFICIAL_FIELDS = (
    "first_name",
    "last_name",
    "job_title",
    "company",
    "location",
    "phone_number",
    "email",
)


def _comparable(value: object) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()).casefold()


def score_dataset(
    expected_records: dict[str, dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    totals = {"correct": 0, "partial": 0, "failed": 0}
    per_card: dict[str, dict[str, str]] = {}
    for card_name, record in expected_records.items():
        expected = record["expected"]
        predicted = predictions.get(card_name, {})
        field_results: dict[str, str] = {}
        for field in OFFICIAL_FIELDS:
            expected_value = _comparable(expected.get(field))
            predicted_value = _comparable(predicted.get(field))
            if predicted_value == expected_value:
                result = "correct"
            elif predicted_value is None and expected_value is not None:
                result = "failed"
            else:
                result = "partial"
            totals[result] += 1
            field_results[field] = result
        per_card[card_name] = field_results

    field_count = len(expected_records) * len(OFFICIAL_FIELDS)
    return {
        "cards_tested": len(expected_records),
        "fields_expected": field_count,
        "correct_fields": totals["correct"],
        "partial_fields": totals["partial"],
        "failed_fields": totals["failed"],
        "accuracy": totals["correct"] / field_count if field_count else 0.0,
        "per_card": per_card,
    }


async def run_evaluation(base_url: str, manifest_path: Path) -> dict[str, Any]:
    manifest_text = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
    records = json.loads(manifest_text)
    predictions: dict[str, dict[str, Any]] = {}
    cards_directory = manifest_path.parent / "cards"
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=180) as client:
        created = await client.post("/api/batches", json={"total_cards": len(records)})
        created.raise_for_status()
        batch_id = created.json()["id"]
        for name, record in records.items():
            path = cards_directory / record["filename"]
            try:
                image = await asyncio.to_thread(path.read_bytes)
                response = await client.post(
                    f"/api/batches/{batch_id}/cards",
                    files={"file": (path.name, image, "image/png")},
                )
                response.raise_for_status()
                payload = response.json()
                predictions[name] = {
                    field: payload.get(field) for field in OFFICIAL_FIELDS
                }
            except (httpx.HTTPError, ValueError):
                predictions[name] = {field: None for field in OFFICIAL_FIELDS}
    return score_dataset(records, predictions)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure field-level extraction accuracy on synthetic cards."
    )
    parser.add_argument("--base-url", required=True, help="Deployed or local application URL")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("evaluation/ground-truth.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional safe report path. Reports contain status labels, never raw model text.",
    )
    arguments = parser.parse_args()
    report = asyncio.run(run_evaluation(arguments.base_url, arguments.manifest))
    serialized = json.dumps(report, indent=2) + "\n"
    if arguments.report:
        arguments.report.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
