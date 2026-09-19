from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx


async def benchmark(base_url: str, cards: list[Path]) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(2)
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=180) as client:
        created = await client.post("/api/batches", json={"total_cards": len(cards)})
        created.raise_for_status()
        batch_id = created.json()["id"]

        async def upload(path: Path) -> dict[str, object]:
            async with semaphore:
                started = perf_counter()
                card_bytes = await asyncio.to_thread(path.read_bytes)
                response = await client.post(
                    f"/api/batches/{batch_id}/cards",
                    files={"file": (path.name, card_bytes, "image/png")},
                )
                response.raise_for_status()
                return {
                    "card": path.name,
                    "latency_seconds": round(perf_counter() - started, 3),
                    "status": response.json()["status"],
                }

        batch_started = perf_counter()
        results = await asyncio.gather(*(upload(path) for path in cards))
        return {
            "batch_id": batch_id,
            "cards": len(cards),
            "concurrency": 2,
            "batch_latency_seconds": round(perf_counter() - batch_started, 3),
            "results": results,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure a five-card deployed batch without exposing real contact data."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cards-dir", type=Path, default=Path("evaluation/cards"))
    arguments = parser.parse_args()
    cards = sorted(arguments.cards_dir.glob("*.png"))[:5]
    if len(cards) != 5:
        raise SystemExit("Five synthetic PNG cards are required")
    print(json.dumps(asyncio.run(benchmark(arguments.base_url, cards)), indent=2))


if __name__ == "__main__":
    main()
