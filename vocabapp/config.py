from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from anki_client.client import ANKI_URL

_PROJECT_ROOT = Path(__file__).parent.parent


class AppSettings(BaseModel):
    """Settings for the web app itself.

    LLM credentials still come from ``anki_client.config.get_settings()`` —
    this only covers what the web app adds on top.
    """

    anki_url: str = ANKI_URL
    default_deck: str = "QA"
    db_path: Path = _PROJECT_ROOT / "vocabapp.db"
    quiz_size: int = 8
    frontend_dist: Path = _PROJECT_ROOT / "frontend" / "dist"


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()
