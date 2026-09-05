from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from anki_client.client import ANKI_URL

_PROJECT_ROOT = Path(__file__).parent.parent


class AppSettings(BaseSettings):
    """Settings for the web app itself.

    LLM credentials still come from ``anki_client.config.get_settings()`` —
    this only covers what the web app adds on top. Every field is overridable
    via a ``VOCABAPP_``-prefixed environment variable; ``VOCABAPP_DB_PATH`` in
    particular lets the web UI and the MCP server share one review queue even
    when they are launched from different checkouts.
    """

    model_config = SettingsConfigDict(env_prefix="VOCABAPP_", extra="ignore")

    anki_url: str = ANKI_URL
    default_deck: str = "QA"
    db_path: Path = _PROJECT_ROOT / "vocabapp.db"
    quiz_size: int = 8
    frontend_dist: Path = _PROJECT_ROOT / "frontend" / "dist"
    # Shown to agents so they can point a human at the review queue.
    web_url: str = "http://localhost:8000"


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()
