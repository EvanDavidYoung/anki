# Anki Project

## Summary

A `uv`-managed Python library (`anki_client`) that wraps AnkiConnect and Claude to support common Anki workflows: card generation from content sources (local files, RSS feeds), learning progress stats, and editing existing cards. An MCP server built on top exposes the same functionality conversationally in Claude sessions.

## Card Generation Workflow

**Before generating or adding any cards**, always follow these steps:

1. Call `list_decks_with_note_types` to get the current deck list with their note types.
2. Present the results and ask the user which deck's format they want to use.
3. Once the user picks a deck, call `get_note_type_fields` with that deck's note type to see the exact fields.
4. Generate cards matching those fields.
5. Add cards to the **QA** deck (not the format-reference deck). All card-creation tools default to `deck="QA"`.
