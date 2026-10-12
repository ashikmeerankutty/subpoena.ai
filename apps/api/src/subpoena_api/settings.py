from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_PEPPER = "dev-only-pepper-change-me"
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBPOENA_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "demo", "prod"] = "local"
    store: Literal["memory", "firestore"] = "memory"
    publisher: Literal["memory", "log", "pubsub"] = "log"
    baselines: Literal["seed", "firestore"] = "seed"
    gcp_project: str | None = None
    firestore_database: str = "(default)"
    pubsub_topic: str = "evaluations.created"
    api_key_pepper: SecretStr = SecretStr(DEV_PEPPER)
    seed_dir: Path = REPO_ROOT / "data" / "seed"
    idempotency_ttl_hours: int = 24
    public_base_url: str = "http://localhost:8000"  # used to validate Twilio signatures
    twilio_auth_token: SecretStr | None = None
    demo_scenarios: bool = True
    witness_simulator: bool = True  # Console phone simulator; disable with real Twilio
    webhook_signing_secret: SecretStr = SecretStr("dev-only-webhook-secret")
    sync_poll_interval_ms: int = 250
    sync_wait_max_ms: int = 30000
    google_client_id: str | None = None  # enables Console sign-in with Google
    twilio_account_sid: str | None = None  # needed to download photos witnesses send
    media_store: Literal["memory", "gcs"] = "memory"
    media_bucket: str | None = None
    max_media_bytes: int = 5_000_000

    @property
    def key_mode(self) -> str:
        return "live" if self.env in ("demo", "prod") else "test"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if (
        settings.env in ("demo", "prod")
        and settings.api_key_pepper.get_secret_value() == DEV_PEPPER
    ):
        raise RuntimeError("SUBPOENA_API_KEY_PEPPER must be set outside local/test")
    return settings
