from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict

PROMPT = """Extract ONLY information visible on this business card. Do not infer missing
details. Return one JSON object with exactly these seven keys: first_name, last_name,
job_title, company, location, phone_number, email. Every value must be a string or null.
Do not return confidence, reasoning, totals, warnings, markdown, or any additional key."""

OFFICIAL_FIELDS = (
    "first_name",
    "last_name",
    "job_title",
    "company",
    "location",
    "phone_number",
    "email",
)


class BenchmarkLead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None
    last_name: str | None
    job_title: str | None
    company: str | None
    location: str | None
    phone_number: str | None
    email: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Qwen VLM on an AWS CPU host.")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-2B-Instruct")
    parser.add_argument(
        "--image",
        type=Path,
        default=Path("evaluation/cards/clean-horizontal.png"),
    )
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1))
    parser.add_argument("--max-new-tokens", type=int, default=350)
    return parser.parse_args()


def parse_model_json(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```json") and candidate.endswith("```"):
        candidate = candidate[7:-3].strip()
    elif candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or any(field not in value for field in OFFICIAL_FIELDS):
        return None
    try:
        return BenchmarkLead.model_validate(value).model_dump()
    except ValueError:
        return None


def peak_rss_mb() -> float:
    # VmHWM is the peak resident set in KiB; this benchmark is AWS/Linux-only.
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return float(line.split()[1]) / 1024
    raise RuntimeError("Linux peak-memory metric VmHWM was unavailable")


def main() -> None:
    args = parse_args()
    if args.threads < 1:
        raise SystemExit("--threads must be at least 1")
    if not args.image.is_file():
        raise SystemExit(f"image not found: {args.image}")

    import torch
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    dtype = {"bfloat16": torch.bfloat16, "float32": torch.float32}[args.dtype]

    started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(args.model)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        args.model,
        dtype=dtype,
        device_map="cpu",
        low_cpu_mem_usage=True,
    )
    model.eval()
    load_seconds = time.perf_counter() - started

    with Image.open(args.image) as source:
        image = source.convert("RGB")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": PROMPT},
            ],
        }
    ]
    rendered = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = processor(text=[rendered], images=[image], return_tensors="pt")

    started = time.perf_counter()
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
            repetition_penalty=1.02,
        )
    inference_seconds = time.perf_counter() - started
    trimmed = generated[:, inputs.input_ids.shape[1] :]
    raw_output = processor.batch_decode(
        trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]
    image.close()

    result = {
        "model": args.model,
        "device": "cpu",
        "dtype": args.dtype,
        "threads": args.threads,
        "load_seconds": round(load_seconds, 3),
        "inference_seconds": round(inference_seconds, 3),
        "peak_rss_mb": round(peak_rss_mb(), 1),
        "structured_output_valid": parse_model_json(raw_output) is not None,
        "output": parse_model_json(raw_output) or raw_output[:2000],
    }
    print("O_HIVE_CPU_BENCHMARK=" + json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
