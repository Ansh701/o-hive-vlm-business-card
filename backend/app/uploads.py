from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from PIL import Image, UnidentifiedImageError

from backend.app.config import Settings

ALLOWED_EXTENSIONS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
SAFE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class UploadValidationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    content: bytes
    sha256: str
    media_type: str
    safe_suffix: str
    display_filename: str
    width: int
    height: int


def display_filename(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name
    printable = "".join(character for character in name if character.isprintable())
    return (printable.strip() or "business-card")[:255]


def _raise_invalid_image() -> None:
    raise UploadValidationError(
        "invalid_image",
        "This file is not a readable image. Upload a valid JPG, PNG, or WEBP card.",
    )


def validate_image(filename: str, content: bytes, settings: Settings) -> ValidatedImage:
    """Decode and re-encode an allowed image so metadata and trailing payloads are dropped."""

    safe_display_name = display_filename(filename)
    suffix = PurePosixPath(safe_display_name.lower()).suffix
    expected_format = ALLOWED_EXTENSIONS.get(suffix)
    if expected_format is None:
        raise UploadValidationError(
            "unsupported_type", "Only JPG, PNG, or WEBP business-card images are supported."
        )
    if not content:
        raise UploadValidationError("empty_file", "The selected image is empty.")
    if len(content) > settings.max_file_bytes:
        limit_mb = settings.max_file_bytes / (1024 * 1024)
        raise UploadValidationError(
            "file_too_large", f'This image is larger than the {limit_mb:g} MB per-card limit.'
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as candidate:
                detected_format = candidate.format
                width, height = candidate.size
                candidate.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise UploadValidationError(
            "decompression_bomb", "The image exceeds the safe pixel limit. Resize it and try again."
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        _raise_invalid_image()
        raise AssertionError("unreachable") from exc

    if detected_format != expected_format:
        raise UploadValidationError(
            "format_mismatch",
            "The filename extension does not match the decoded "
            f"{detected_format or 'image'} format.",
        )
    if width * height > settings.max_image_pixels:
        raise UploadValidationError(
            "image_too_large",
            "This image contains too many pixels. Resize it to a smaller resolution and try again.",
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as decoded:
                decoded.load()
                if detected_format == "JPEG":
                    safe_image = decoded.convert("RGB")
                elif decoded.mode not in {"RGB", "RGBA", "L", "LA"}:
                    target_mode = "RGBA" if "transparency" in decoded.info else "RGB"
                    safe_image = decoded.convert(target_mode)
                else:
                    safe_image = decoded.copy()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise UploadValidationError(
            "decompression_bomb", "The image exceeds the safe pixel limit. Resize it and try again."
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        _raise_invalid_image()
        raise AssertionError("unreachable") from exc

    output = BytesIO()
    save_options: dict[str, int | bool] = {}
    if detected_format == "JPEG":
        save_options = {"quality": 90, "optimize": True}
    elif detected_format == "WEBP":
        save_options = {"quality": 90, "method": 4}
    safe_image.save(output, format=detected_format, **save_options)
    safe_image.close()

    return ValidatedImage(
        content=output.getvalue(),
        sha256=hashlib.sha256(content).hexdigest(),
        media_type=MEDIA_TYPES[detected_format],
        safe_suffix=SAFE_SUFFIXES[detected_format],
        display_filename=safe_display_name,
        width=width,
        height=height,
    )
