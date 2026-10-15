from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
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
    rag_enabled: bool = False
    rag_data_dir: Path = Path("./data/rag")
    # JSON mapping opaque API credentials to server-controlled tenant/user/scopes.
    rag_api_tokens: SecretStr = SecretStr("{}")
    identity_encryption_key: SecretStr = SecretStr("")
    identity_lookup_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1-mini"
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_api_key: SecretStr = SecretStr("")
    elasticsearch_index: str = "metriks-chunks-multilingual-v2"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    default_query_language: Literal["en", "it"] = "en"
    ocr_enabled: bool = True
    ocr_language: str = "eng+ita"
    max_pdf_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_pdf_pages: int = Field(default=300, ge=1)
    session_ttl_seconds: int = Field(default=86400, ge=60)
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
