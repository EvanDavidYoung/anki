import openai

from .config import Settings, get_settings


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        self._client = openai.OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key)
        self._model = s.llm_model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""
