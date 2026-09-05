import openai

from .config import Settings, get_settings


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        """Any of model/base_url/api_key may be overridden so a single caller
        can talk to a different provider than the project default."""
        s = settings or get_settings()
        self._client = openai.OpenAI(
            base_url=base_url or s.llm_base_url,
            api_key=api_key or s.llm_api_key,
        )
        self._model = model or s.llm_model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""
