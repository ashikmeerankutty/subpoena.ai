from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBPOENA_", env_file=".env", extra="ignore")

    data: Literal["seed", "bigquery"] = "seed"
    store: Literal["memory", "firestore"] = "memory"
    gcp_project: str | None = None
    firestore_database: str = "(default)"
    bq_dataset: str = "subpoena"
    seed_dir: Path = REPO_ROOT / "data" / "seed"

    witness_channel: Literal["simulator", "twilio"] = "simulator"
    sim_swap_window_days: int = 7
    agent_token_secret: SecretStr = SecretStr("dev-only-agent-secret")

    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_messaging_service_sid: str | None = None
    twilio_whatsapp_from: str | None = None  # e.g. whatsapp:+14155238886 (sandbox)
    twilio_whatsapp_content_sid: str | None = None  # approved subpoena template
    twilio_verify_service_sid: str | None = None
    twilio_status_callback_url: str | None = None
