from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with cost and upload limits kept in one place."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+aiosqlite:///./o_hive.db"
    frontend_dist: Path = Path("frontend/dist")

    max_cards_per_batch: int = Field(default=20, ge=1, le=50)
    max_file_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    max_total_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=250 * 1024 * 1024)
    max_image_pixels: int = Field(default=24_000_000, ge=1_000_000, le=80_000_000)
    inference_concurrency: int = Field(default=2, ge=1, le=4)
    inference_timeout_seconds: float = Field(default=75.0, ge=5.0, le=180.0)
    max_daily_cards: int = Field(default=200, ge=1, le=10_000)
    temp_directory: Path | None = None

    aws_inference_endpoint: str | None = None
    aws_inference_shared_secret: SecretStr | None = None
    qwen_model: str = "Qwen/Qwen3-VL-2B-Instruct"

    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    batch_creations_per_minute: int = Field(default=10, ge=1, le=120)
    card_requests_per_minute: int = Field(default=30, ge=1, le=300)

    @field_validator("database_url", mode="before")
    @classmethod
    def require_async_database_driver(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("DATABASE_URL must be a string")
        if value.startswith("postgres://"):
            value = "postgresql+asyncpg://" + value.removeprefix("postgres://")
        elif value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        if not value.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError("DATABASE_URL must use asyncpg or aiosqlite")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
