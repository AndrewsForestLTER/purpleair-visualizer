"""Remember the Download tab's choices between sessions."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path.home() / ".purpleair_visualizer" / "settings.json"
API_KEY_VARIABLE = "PURPLEAIR_API_KEY"


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    """Read saved settings.

    Args:
        path: The settings file.

    Returns:
        The saved settings, or an empty dict if none can be read.
    """
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        logger.warning("Ignoring unreadable settings file: %s", error)
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    """Write settings where only the current user should be able to read them.

    Args:
        settings: The values to save.
        path: The settings file.

    Raises:
        OSError: If the file cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
    temporary.replace(path)


def initial_api_key(settings: dict[str, Any]) -> str:
    """Return the saved API key, falling back to the environment variable."""
    return str(settings.get("api_key") or os.environ.get(API_KEY_VARIABLE, ""))
