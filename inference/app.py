from __future__ import annotations

import asyncio
import base64
import binascii
import os
import time
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inference.security import SignatureError, verify_signature

MODEL_ID = os.getenv("QWEN_MODEL", "Qwen/Qwen3-VL-2B-Instruct")
SHARED_SECRET = os.getenv("INFERENCE_SHARED_SECRET", "")
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
PRELOAD_MODEL = os.getenv("PRELOAD_MODEL", "true").lower() == "true"
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_base64: str = Field(max_length=12_000_000)
    media_type: str
    prompt: str = Field(min_length=50, max_length=8000)
    previous_output: str | None = Field(default=None, max_length=4000)


class ExtractionResponse(BaseModel):
    output: str


class QwenRuntime:
    def __init__(self) -> None:
        self.model: Any = None
        self.processor: Any = None
        self._load_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self.model is not None and self.processor is not None

    async def load(self) -> None:
        if self.loaded:
            return
        async with self._load_lock:
            if self.loaded:
                return
            await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> None:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for the configured AWS inference service")
        self.processor = AutoProcessor.from_pretrained(MODEL_ID)
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            MODEL_ID,
            dtype=torch.bfloat16,
            device_map="cuda",
            low_cpu_mem_usage=True,
        )
        self.model.eval()

    async def generate(self, image_bytes: bytes, prompt: str) -> str:
        await self.load()
        async with self._inference_lock:
            return await asyncio.to_thread(self._generate_sync, image_bytes, prompt)

    def _generate_sync(self, image_bytes: bytes, prompt: str) -> str:
        import torch

        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        rendered = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(text=[rendered], images=[image], return_tensors="pt")
        inputs = inputs.to(self.model.device)
        with torch.inference_mode():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=700,
                do_sample=False,
                repetition_penalty=1.02,
            )
        trimmed = generated[:, inputs.input_ids.shape[1] :]
        result = self.processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        image.close()
        return result


runtime = QwenRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if PRELOAD_MODEL:
        await runtime.load()
    yield


app = FastAPI(
    title="O-HIVE Qwen inference",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/ready")
async def ready() -> dict[str, str | bool]:
    if not runtime.loaded:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model loading")
    return {"status": "ready", "model": MODEL_ID, "loaded": True}


@app.post("/v1/extract", response_model=ExtractionResponse)
async def extract(request: Request) -> ExtractionResponse:
    if not SHARED_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="inference authentication is not configured",
        )
    body = await request.body()
    try:
        verify_signature(
            SHARED_SECRET,
            request.headers.get("x-o-hive-timestamp", ""),
            request.headers.get("x-o-hive-signature", ""),
            body,
            now=int(time.time()),
        )
    except SignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    try:
        payload = ExtractionRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid request"
        ) from exc
    if payload.media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="unsupported image"
        )
    try:
        image_bytes = base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid image data"
        ) from exc
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="image too large"
        )
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid image"
        ) from exc

    output = await runtime.generate(image_bytes, payload.prompt)
    return ExtractionResponse(output=output)
