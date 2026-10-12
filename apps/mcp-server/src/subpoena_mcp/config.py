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
    embeddings: Literal["hash", "vertex"] = "hash"  # precedent search
    embedding_model: str = "text-embedding-005"
    embedding_location: str = "us-central1"
    sim_swap_window_days: int = 7
    # Fail closed when the carrier cannot report SIM-swap status (Twilio trial accounts can't).
    sim_swap_required: bool = True
    agent_token_secret: SecretStr = SecretStr("dev-only-agent-secret")

    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_messaging_service_sid: str | None = None
    twilio_whatsapp_from: str | None = None  # e.g. whatsapp:+14155238886 (sandbox)
    twilio_whatsapp_content_sid: str | None = None  # approved subpoena template
    twilio_verify_service_sid: str | None = None
    twilio_status_callback_url: str | None = None
    # Comma-separated E.164 numbers routed to Twilio; empty = all. Others use the simulator,
    # so seeded demo witnesses keep working next to a real phone.
    twilio_live_numbers: str = ""
    # If Twilio rejects a witness message (e.g. no WhatsApp sender yet), deliver it to the
    # Console phone simulator instead; one-time codes still go through Twilio Verify.
    twilio_message_fallback: bool = False

    @property
    def live_numbers(self) -> frozenset[str]:
        return frozenset(n.strip() for n in self.twilio_live_numbers.split(",") if n.strip())
