from __future__ import annotations

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CourtSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBPOENA_", env_file=".env", extra="ignore")

    store: Literal["memory", "firestore"] = "memory"
    firestore_database: str = "(default)"
    llm: Literal["gemini", "scripted"] = "scripted"
    gcp_project: str | None = None
    vertex_location: str = "global"
    flash_model: str = "gemini-2.5-flash"
    pro_model: str = "gemini-2.5-pro"
    flash_fallback_model: str | None = "gemini-2.5-flash-lite"
    judge_fallback_model: str | None = "gemini-2.5-flash"
    max_concurrent_llm_calls: int = 4
    judge_thinking_budget: int = 512
    temperature: float = 0.0
    max_output_tokens: int = 2048
    max_rounds: int = 2  # opening arguments + (max_rounds - 1) rebuttal rounds

    mcp: Literal["inprocess", "http"] = "inprocess"
    mcp_url: str | None = None
    mcp_audience: str | None = None  # Cloud Run IAM audience for the MCP service
    agent_token_secret: SecretStr = SecretStr("dev-only-agent-secret")

    screening: Literal["heuristic", "model_armor"] = "heuristic"
    model_armor_template: str | None = None  # projects/../locations/../templates/..
    model_armor_location: str = "us-central1"

    webhook_signing_secret: SecretStr = SecretStr("dev-only-webhook-secret")
    daily_case_cap: int = 300  # cost governor: courtroom cases per workspace per day

    media_store: Literal["memory", "gcs"] = "memory"  # witness photos (receipts)
    media_bucket: str | None = None
