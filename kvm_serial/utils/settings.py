import configparser
import os
import logging
from typing import Dict, Any


def load_settings(
    config_file: str, section: str, defaults: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """
    Load settings from an INI file. Returns a dict of settings for the given section.
    If the file or section does not exist, returns defaults (if provided) or empty dict.
    """
    config = configparser.ConfigParser()
    if not os.path.exists(config_file):
        return defaults.copy() if defaults is not None else {}
    config.read(config_file)
    if section not in config:
        return defaults.copy() if defaults is not None else {}
    settings = dict(config[section])
    # Overlay defaults for missing keys
    if defaults is not None:
        for k, v in defaults.items():
            settings.setdefault(k, v)
    logging.info(f"Settings loaded from {config_file} [{section}]")
    return settings


def save_settings(config_file: str, section: str, settings: Dict[str, Any]) -> None:
    """
    Save settings to an INI file under the given section.
    """
    config = configparser.ConfigParser()
    if os.path.exists(config_file):
        config.read(config_file)
    config[section] = {k: str(v) for k, v in settings.items()}
    with open(config_file, "w") as f:
        config.write(f)
    logging.info(f"Settings saved to {config_file} [{section}]")
