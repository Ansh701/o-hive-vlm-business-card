from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

from backend.app.config import Settings
from backend.app.inference import InferenceClient
from backend.app.uploads import validate_image


async def smoke(card_path: Path) -> dict[str, object]:
    settings = Settings()
    card_bytes = await asyncio.to_thread(card_path.read_bytes)
    validated = validate_image(card_path.name, card_bytes, settings)
    started = perf_counter()
    lead = await InferenceClient(settings).extract(validated.content, validated.media_type)
    return {
        "model": settings.qwen_model,
        "latency_seconds": round(perf_counter() - started, 3),
        "lead": lead.model_dump(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one authenticated extraction against the AWS-hosted Qwen endpoint."
    )
    parser.add_argument(
        "--card",
        type=Path,
        default=Path("evaluation/cards/clean-horizontal.png"),
    )
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(smoke(arguments.card)), indent=2))


if __name__ == "__main__":
    main()
