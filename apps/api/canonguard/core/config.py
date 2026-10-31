from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CANONGUARD_",
        extra="ignore",
    )

    app_name: str = "CanonGuard"
    environment: str = "local"
    api_host: str = "127.0.0.1"
    api_port: int = 8100

    database_url: str = "sqlite:///./canonguard.db"
    auto_create_tables: bool = True

    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "canonguard"

    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "canonguard"
    minio_secret_key: str = "canonguard"
    minio_secure: bool = False
    minio_bucket_sources: str = "canonguard-sources"
    minio_bucket_artifacts: str = "canonguard-artifacts"

    valkey_url: str = "redis://127.0.0.1:6379/0"

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    llm_extractor_model: str = ""
    llm_gap_model: str = ""
    llm_planner_model: str = ""
    llm_writer_model: str = ""
    llm_reviewer_model: str = ""
    llm_auditor_model: str = ""
    llm_judge_model: str = ""
    # Auto mode tries this provider first; the other becomes the fallback.
    model_preference: Literal["deepseek", "qwen"] = "deepseek"
    llm_request_timeout_seconds: int = 120
    llm_max_repairs: int = 2

    run_max_tokens: int = 200_000
    run_max_cost_usd: float = 5.0
    # USD per 1M tokens. 0 means "use the built-in estimate for known models".
    # Set these when the provider/model is not in litellm's price table.
    llm_price_input_per_1m: float = 0.0
    llm_price_output_per_1m: float = 0.0
    prompt_version: str = "phase0"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
