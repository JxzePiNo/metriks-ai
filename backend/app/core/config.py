from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings, loaded from environment variables (or `.env`)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Metriks AI API"
    app_env: Literal["local", "test", "production"] = Field(
        default="local", validation_alias="APP_ENV"
    )
    log_level: LogLevel = Field(default="INFO", validation_alias="LOG_LEVEL")
    # Browser origins allowed to call the API (comma-separated). Empty disables CORS.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list, validation_alias="CORS_ORIGINS"
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("CORS_ORIGINS must list explicit origins, not '*'")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
