from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tomllib


class ConfigurationError(ValueError):
    """Raised when importer configuration cannot be used."""


@dataclass(frozen=True)
class FeedCatalog:
    """A topic-focused OPML file selected for an import run."""

    id: str
    path: Path
    enabled: bool = True
    folder: str | None = None


@dataclass(frozen=True)
class ImporterConfig:
    vault_path: Path | None
    articles_path: Path
    defuddle_executable: str
    lookback_days: int = 90
    feed_catalogs: tuple[FeedCatalog, ...] = ()
    disabled_sources: frozenset[str] = frozenset()
    max_attempts: int = 3


def load_config(path: Path) -> ImporterConfig:
    """Load and validate the importer configuration at *path*."""
    config_path = path.resolve()
    try:
        with config_path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
            importer = raw_config.get("importer")
        if not isinstance(importer, dict):
            raise ConfigurationError("importer must be a TOML table")
    except (ConfigurationError, OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"Unable to read importer configuration: {error}") from error

    output_value = importer.get("output_path")
    vault_value = importer.get("vault_path")
    if output_value is not None:
        if not isinstance(output_value, str) or not output_value:
            raise ConfigurationError("importer.output_path must be a non-empty string")
        vault_path = None
        articles_path = _resolve_path(output_value, config_path.parent)
        if not articles_path.is_dir():
            raise ConfigurationError(f"Configured output directory does not exist: {articles_path}")
    else:
        if not isinstance(vault_value, str) or not vault_value:
            raise ConfigurationError(
                "importer.output_path or importer.vault_path must be a non-empty string"
            )
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

    max_attempts = importer.get("max_attempts", 3)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts <= 0:
        raise ConfigurationError("importer.max_attempts must be a positive integer")

    catalogs = _read_catalogs(raw_config, config_path.parent)
    disabled_sources = _read_disabled_sources(raw_config)
    return ImporterConfig(
        vault_path,
        articles_path,
        str(executable_path),
        lookback_days,
        catalogs,
        disabled_sources,
        max_attempts,
    )


def _resolve_path(value: str, base_path: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_path / path).resolve()


def _resolve_executable(value: str, base_path: Path) -> str:
    """Resolve explicit executable paths while retaining bare PATH commands."""
    path = Path(value)
    if path.is_absolute() or "/" in value or "\\" in value:
        return str(_resolve_path(value, base_path))
    return shutil.which(value) or value


def _read_catalogs(config: dict[str, object], base_path: Path) -> tuple[FeedCatalog, ...]:
    values = config.get("feed_catalogs", [])
    if not isinstance(values, list):
        raise ConfigurationError("feed_catalogs must be an array of TOML tables")

    disabled_catalogs = _read_disabled_catalogs(config)
    catalogs: list[FeedCatalog] = []
    seen_ids: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise ConfigurationError("each feed_catalogs entry must be a TOML table")
        catalog_id = value.get("id")
        catalog_path = value.get("path")
        enabled = value.get("enabled", True)
        folder = value.get("folder")
        if not isinstance(catalog_id, str) or not catalog_id.strip():
            raise ConfigurationError("feed_catalogs.id must be a non-empty string")
        if not isinstance(catalog_path, str) or not catalog_path.strip():
            raise ConfigurationError("feed_catalogs.path must be a non-empty string")
        if not isinstance(enabled, bool):
            raise ConfigurationError("feed_catalogs.enabled must be a boolean")
        if folder is not None and (not isinstance(folder, str) or not folder.strip()):
            raise ConfigurationError("feed_catalogs.folder must be a non-empty string")
        if not enabled or catalog_id in disabled_catalogs:
            continue
        if catalog_id in seen_ids:
            raise ConfigurationError(f"duplicate enabled feed catalog id: {catalog_id}")
        seen_ids.add(catalog_id)
        catalogs.append(
            FeedCatalog(
                catalog_id,
                _resolve_path(catalog_path, base_path),
                True,
                folder,
            )
        )
    return tuple(catalogs)


def _read_disabled_catalogs(config: dict[str, object]) -> frozenset[str]:
    catalog_settings = config.get("feed_catalog", {})
    if not isinstance(catalog_settings, dict):
        raise ConfigurationError("feed_catalog must be a TOML table")
    return _read_string_list(
        catalog_settings.get("disabled_catalogs", []), "feed_catalog.disabled_catalogs"
    )


def _read_disabled_sources(config: dict[str, object]) -> frozenset[str]:
    catalog_settings = config.get("feed_catalog", {})
    if not isinstance(catalog_settings, dict):
        raise ConfigurationError("feed_catalog must be a TOML table")
    return _read_string_list(
        catalog_settings.get("disabled_sources", []), "feed_catalog.disabled_sources"
    )


def _read_string_list(value: object, name: str) -> frozenset[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConfigurationError(f"{name} must be an array of non-empty strings")
    return frozenset(value)
