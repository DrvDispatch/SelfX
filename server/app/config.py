"""Application settings — every env var from SPEC §3, read via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # --- core ---
    selfx_secret_key: str = "change-me-long-random"
    selfx_admin_user: str = "admin"
    selfx_admin_password: str = "change-me"
    database_url: str = "postgresql+psycopg://selfx:selfx@db:5432/selfx"
    redis_url: str = "redis://redis:6379/0"
    data_dir: str = "/data"

    # --- limits & retention ---
    max_upload_mb: int = 512
    file_retention_hours: int = 24  # 0 = keep forever
    job_timeout_seconds: int = 1800
    rate_limit_per_minute: int = 60

    # --- integrations ---
    gotenberg_url: str = "http://gotenberg:3000"
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:8b"
    # How long Ollama keeps a model in (V)RAM after a request. "0" unloads immediately;
    # a short idle like "30s"/"2m" stays warm for follow-ups then frees the GPU when idle.
    ollama_keep_alive: str = "30s"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"
    clamav_enabled: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = 3310

    # --- dev convenience (SPEC §10 "non-debug mode") ---
    debug: bool = False

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()


def check_secret_key() -> None:
    """Fail loudly on startup if the JWT secret is unset/default (SPEC §10)."""
    if settings.debug:
        return
    if not settings.selfx_secret_key or settings.selfx_secret_key == "change-me-long-random":
        raise RuntimeError(
            "SELFX_SECRET_KEY is empty or still the default value. "
            "Set a long random secret in the environment (see .env.example)."
        )
