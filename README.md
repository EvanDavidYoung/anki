# anki-client

A Python library and MCP server that wraps [AnkiConnect](https://foosoft.net/projects/anki-connect/) and an LLM to automate Chinese flashcard workflows.

## What it does

- **Card generation** — paste or pipe a Chinese text passage and Claude extracts 5–15 vocabulary words, formats them as Traditional/Pinyin/Meaning cards with example sentences, and adds them to Anki in one shot.
- **Learning stats** — query deck stats (new / learning / due counts), retention rate, review forecast, and hardest/most-lapsed cards.
- **Card editing** — search notes by Anki query syntax, update fields, add/remove tags, and suspend or unsuspend cards.
- **MCP server** — all of the above is exposed as MCP tools so you can drive your Anki collection conversationally inside Claude.

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) for package management
- [Anki](https://apps.ankiweb.net/) desktop app running with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on enabled (default port 8765)
- An LLM API key (OpenAI-compatible endpoint)

## Getting started

```bash
# Clone and enter the repo
git clone <repo-url>
cd anki-client

# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .
```

### Configuration

Copy `.env.example` to `.env` (or set the variables directly) and fill in your values:

```
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o
```

Set the deck names for your own collection in `config.toml`:

```toml
default_deck = "My Chinese Deck"
staging_deck = "Staging"
target_deck  = "My Chinese Deck"
hsk_deck     = "My Chinese Deck::HSK"
study_decks  = ["My Chinese Deck"]
```

Anything set in `.env` overrides `config.toml`, so you can keep the checked-in
file generic and put your personal deck names in `.env`.

### Running the MCP server

```bash
python -m anki_client.mcp_server
```

Then add the server to your Claude configuration to use the tools conversationally.

## Project structure

```
anki_client/
  client.py       # AnkiConnect HTTP client
  generator.py    # LLM-powered card generation
  llm_client.py   # OpenAI-compatible LLM wrapper
  mcp_server.py   # MCP tool definitions
  models.py       # Pydantic models (ChineseCard, DeckStats, etc.)
  config.py       # Settings loaded from .env + config.toml
  stats.py        # Retention, forecast, hard-card, confusion analysis
  sources/        # Content source adapters (files, RSS, etc.)
input/            # Drop source files here for batch processing
output/           # Generated card exports
config.toml       # Deck names and other non-secret config
```

## Note type

Cards are added using a custom Anki note type called **"Chinese Learning Model"** with the following fields:

| Field | Description |
|---|---|
| Key | Auto-incrementing integer ID |
| Traditional | Traditional Chinese characters |
| Pinyin | Tone-marked romanisation |
| Meaning | English definition |
| PartOfSpeech | noun / verb / adjective / etc. |
| SentenceTraditional | Example sentence (Traditional) |
| SentencePinyin | Example sentence (Pinyin) |
| SentenceMeaning | Example sentence (English) |
| WordAudio | Audio field (optional) |
| SentenceAudio | Audio field (optional) |

You must create this note type in Anki before adding cards.

## MCP tools

| Tool | Description |
|---|---|
| `add_card` | Add a single card with all fields specified |
| `generate_cards_from_text` | Generate cards from a Chinese passage via LLM |
| `get_deck_stats` | New / learning / due counts for one or more decks |
| `get_retention_rate` | % of reviews answered correctly in the last N days |
| `get_hard_cards` | Cards with the most lapses |
| `get_review_forecast` | Due today, due this week, new available |
| `search_cards` | Find notes using Anki search syntax |
| `update_note_fields` | Edit fields on a note by ID |
| `add_tags` / `remove_tags` | Manage tags on a set of notes |
| `suspend` / `unsuspend` | Suspend or unsuspend cards |

## License

MIT — see [LICENSE](LICENSE).
