"""
Config persistence for hippomem server.

Loads hippomem_config.json from the same directory as the SQLite DB.
Overlays user-modified settings onto .env defaults.
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "hippomem_config.json"


def _db_dir_from_url(db_url: str) -> Path:
    """Resolve the directory containing the SQLite DB file from db_url."""
    if "sqlite" not in db_url:
        return Path.cwd()
    # sqlite:///path (relative) or sqlite:////absolute/path
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        path_part = db_url[len(prefix) :]
        if not path_part:
            return Path.cwd()
        p = Path(path_part)
        if p.is_absolute():
            return p.parent
        try:
            return p.resolve().parent
        except OSError:
            return Path.home() / ".hippomem"
    return Path.cwd()


def config_path(db_url: str) -> Path:
    """Path to hippomem_config.json in the same directory as the DB."""
    return _db_dir_from_url(db_url) / CONFIG_FILENAME


def load_config_overlay(db_url: str) -> dict[str, Any]:
    """
    Load hippomem_config.json if it exists.
    Returns empty dict if file is missing or invalid.
    """
    path = config_path(db_url)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("Invalid config: %s is not a JSON object", path)
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load config from %s: %s", path, e)
        return {}


def save_config(db_url: str, config: dict[str, Any]) -> None:
    """Persist full config to hippomem_config.json."""
    path = config_path(db_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    logger.info("Config saved to %s", path)
