"""Common utilities for LLM providers."""

import json


def schema_instructions(schema: dict) -> str:
    """Return text instructing the model to reply with JSON matching the schema."""
    return (
        f"You must reply with a valid JSON document matching this JSON Schema, "
        f"and nothing else:\n\n```json\n{json.dumps(schema, indent=2)}\n```"
    )
