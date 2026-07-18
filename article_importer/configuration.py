from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tomllib


class ConfigurationError(ValueError):
    """Raised when importer configuration cannot be used."""


@dataclass(frozen=True)
class ImporterConfig:
    vault_path: Path
    articles_path: Path
    defuddle_executable: str
    lookback_days: int = 90


def load_config(path: Path) -> ImporterConfig:
    """Load and validate the importer configuration at *path*."""
    config_path = path.resolve()
    try:
        with config_path.open("rb") as config_file:
            importer = tomllib.load(config_file).get("importer")
        if not isinstance(importer, dict):
            raise ConfigurationError("importer must be a TOML table")
        vault_value = importer["vault_path"]
    except (ConfigurationError, KeyError, OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"Unable to read importer configuration: {error}") from error

    if not isinstance(vault_value, str) or not vault_value:
        raise ConfigurationError("importer.vault_path must be a non-empty string")

    vault_path = _resolve_path(vault_value, config_path.parent)
    articles_path = vault_path / "Sources" / "Articles"
    if not vault_path.is_dir() or not articles_path.is_dir():
        raise ConfigurationError(
            f"Configured vault must contain Sources/Articles: {vault_path}"
        )

    executable_value = importer.get("defuddle_executable", "defuddle")
    if not isinstance(executable_value, str) or not executable_value:
        raise ConfigurationError("importer.defuddle_executable must be a non-empty string")
    executable_path = _resolve_executable(executable_value, config_path.parent)

    lookback_days = importer.get("lookback_days")
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or lookback_days <= 0:
        raise ConfigurationError("importer.lookback_days must be a positive integer")

    return ImporterConfig(vault_path, articles_path, str(executable_path), lookback_days)


def _resolve_path(value: str, base_path: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_path / path).resolve()


def _resolve_executable(value: str, base_path: Path) -> str:
    """Resolve explicit executable paths while retaining bare PATH commands."""
    path = Path(value)
    if path.is_absolute() or "/" in value or "\\" in value:
        return str(_resolve_path(value, base_path))
    return shutil.which(value) or value
