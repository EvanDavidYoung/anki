from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

_PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        extra="ignore",
    )

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    default_deck: str
    input_dir: Path = _PROJECT_ROOT / "input"
    output_dir: Path = _PROJECT_ROOT / "output"

    # --- Ingestion pipeline (chat logs / podcasts) ---
    chatlog_dir: Path = _PROJECT_ROOT / "input" / "chatlogs"
    # Intermediate message store: parsed chat messages persist here (typed,
    # deduped) before being batched into LLM requests. Doubles as the future
    # web-app backend.
    message_db: Path = _PROJECT_ROOT / "input" / "messages.db"
    # How many text messages to pack into a single card-generation request.
    message_batch_size: int = 25
    staging_deck: str = "Staging"
    target_deck: str = "自己學中文"
    cloze_deck: str = "自己學中文"  # post-MVP; defaults to target_deck
    hsk_deck: str = "Mandarin HSK 1000-5000"
    study_decks: list[str] = [
        "自己學中文",
        "自己學中文::MTC中文課",
        "Evan Chinese Vocab",
        "Mandarin HSK 1000-5000",
    ]
    vision_model: str = ""  # post-MVP; vision-capable model id for image OCR

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=str(_PROJECT_ROOT / "config.toml")),
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
