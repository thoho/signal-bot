from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    signal_api_url: str = Field(default="http://localhost:8080")
    signal_number: str = Field(default="")
    poll_enabled: bool = Field(default=False)
    poll_timeout_seconds: int = Field(default=10)
    poll_interval_seconds: float = Field(default=0.2)
    max_messages: int = Field(default=10)
    max_message_age_seconds: int = Field(default=0, ge=0)
    send_read_receipts: bool = Field(default=True)
    ignore_attachments: bool = Field(default=False)
    transcription_api_url: str = Field(
        default="https://models.think.evroc.com/v1/audio/transcriptions"
    )
    transcription_api_key: str = Field(default="")
    transcription_model: str = Field(default="KBLab/kb-whisper-large")
    transcription_task: str = Field(default="transcribe")
    master_orchestrator_enabled: bool = Field(default=True)
    master_orchestrator_url: str = Field(default="http://127.0.0.1:8787")
    master_orchestrator_timeout_seconds: float = Field(default=30.0)
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()
