from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from backend.app.config import Settings
from backend.app.uploads import UploadValidationError, validate_image


def image_bytes(
    image_format: str = "PNG", size: tuple[int, int] = (640, 360), color: str = "white"
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "image_format", "expected_media"),
    [
        ("card.jpg", "JPEG", "image/jpeg"),
        ("card.jpeg", "JPEG", "image/jpeg"),
        ("card.png", "PNG", "image/png"),
        ("card.webp", "WEBP", "image/webp"),
    ],
)
def test_valid_image_is_decoded_reencoded_and_hashed(
    filename: str, image_format: str, expected_media: str
) -> None:
    validated = validate_image(filename, image_bytes(image_format), Settings())

    assert validated.media_type == expected_media
    assert validated.width == 640
    assert validated.height == 360
    assert len(validated.sha256) == 64
    assert validated.safe_suffix in {".jpg", ".png", ".webp"}
    Image.open(BytesIO(validated.content)).verify()


def test_unsupported_extension_is_rejected_before_decode() -> None:
    with pytest.raises(UploadValidationError, match="JPG, PNG, or WEBP") as error:
        validate_image("card.svg", image_bytes(), Settings())

    assert error.value.code == "unsupported_type"


def test_fake_jpeg_is_rejected_by_decoded_content() -> None:
    with pytest.raises(UploadValidationError, match="not a readable image") as error:
        validate_image("totally-real.jpg", b"<html><script>alert(1)</script>", Settings())

    assert error.value.code == "invalid_image"


def test_extension_must_match_decoded_format() -> None:
    with pytest.raises(UploadValidationError, match="does not match") as error:
        validate_image("card.jpg", image_bytes("PNG"), Settings())

    assert error.value.code == "format_mismatch"


def test_oversized_file_is_rejected_without_decoding() -> None:
    settings = Settings(max_file_bytes=1024)
    payload = image_bytes("PNG", size=(600, 600), color="#123456") + b"x" * 1024

    with pytest.raises(UploadValidationError, match="larger than") as error:
        validate_image("large.png", payload, settings)

    assert error.value.code == "file_too_large"


def test_oversized_pixel_dimensions_are_rejected() -> None:
    settings = Settings(max_image_pixels=1_000_000)

    with pytest.raises(UploadValidationError, match="too many pixels") as error:
        validate_image("huge.png", image_bytes(size=(1001, 1000)), settings)

    assert error.value.code == "image_too_large"


def test_low_resolution_image_is_rejected_before_inference() -> None:
    with pytest.raises(UploadValidationError, match="resolution is too low") as error:
        validate_image("tiny.png", image_bytes(size=(64, 64)), Settings())

    assert error.value.code == "image_too_small"


def test_decompression_bomb_warning_is_treated_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)

    with pytest.raises(UploadValidationError, match="safe pixel limit") as error:
        validate_image("bomb.png", image_bytes(size=(100, 100)), Settings())

    assert error.value.code == "decompression_bomb"


def test_empty_file_is_rejected() -> None:
    with pytest.raises(UploadValidationError, match="empty") as error:
        validate_image("empty.png", b"", Settings())

    assert error.value.code == "empty_file"


def test_source_filename_is_display_only_not_a_generated_path() -> None:
    validated = validate_image("../../private/card.png", image_bytes(), Settings())

    assert validated.display_filename == "card.png"
    assert ".." not in validated.display_filename
    assert "/" not in validated.display_filename
    assert "\\" not in validated.display_filename
