"""Runtime configuration, loaded once from the environment.

Every budget and threshold in the system is declared here rather than inline, so that an
eval run can record the exact configuration that produced a result (see ADR-017).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    model_resolution: str = "claude-sonnet-5-5"
    model_judge: str = "claude-opus-5-5"

    # SQLite by default so the demo runs with no Docker; Postgres works via DATABASE_URL.
    database_url: str = "sqlite:///data/denial_desk.db"
    synthetic_data_dir: str = "data/synthetic"
    reviewer_name: str = "reviewer"

    # Budgets — enforced, not advisory. See ADR-018.
    max_agent_steps: int = 8
    max_tokens_per_claim: int = 40_000
    max_usd_per_claim: float = 0.25

    # Retrieval floor below which the system refuses rather than answers. See ADR-011.
    retrieval_min_score: float = 0.35

    log_redaction: str = "strict"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
