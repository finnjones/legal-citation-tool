"""Loads settings from a `.env` file so API keys and the model choice don't have to be
exported in every shell. Real environment variables always win over the file."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path | None = None) -> None:
    """Read KEY=VALUE lines from `path` (default: ./.env, then the project root .env)."""
    candidates = [Path(path)] if path else [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.removeprefix("export ").strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)
        return
