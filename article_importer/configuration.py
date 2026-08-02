from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
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
class Schedule:
    """A portable local-time ingestion schedule."""

    id: str
    frequency: str
    at: str
    enabled: bool = True
    days: tuple[str, ...] = ()
    day: int | None = None
    date: str | None = None


@dataclass(frozen=True)
class ImporterConfig:
    vault_path: Path | None
    articles_path: Path
    defuddle_executable: str
    lookback_days: int = 90
    feed_catalogs: tuple[FeedCatalog, ...] = ()
    disabled_sources: frozenset[str] = frozenset()
    max_attempts: int = 3
    schedules: tuple[Schedule, ...] = ()


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
    schedules = _read_schedules(raw_config)
    return ImporterConfig(
        vault_path,
        articles_path,
        str(executable_path),
        lookback_days,
        catalogs,
        disabled_sources,
        max_attempts,
        schedules,
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


def _read_schedules(config: dict[str, object]) -> tuple[Schedule, ...]:
    values = config.get("schedules", [])
    if not isinstance(values, list):
        raise ConfigurationError("schedules must be an array of TOML tables")

    schedules: list[Schedule] = []
    seen_ids: set[str] = set()
    common_keys = {"id", "frequency", "at", "enabled"}
    recurrence_keys = {
        "daily": set(),
        "weekly": {"days"},
        "monthly": {"day"},
        "once": {"date"},
    }
    for value in values:
        if not isinstance(value, dict):
            raise ConfigurationError("each schedules entry must be a TOML table")
        schedule_id = value.get("id")
        frequency = value.get("frequency")
        at = value.get("at")
        enabled = value.get("enabled", True)
        if not isinstance(schedule_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]*", schedule_id
        ):
            raise ConfigurationError(
                "schedules.id must use lowercase letters, numbers, and hyphens"
            )
        if schedule_id in seen_ids:
            raise ConfigurationError(f"duplicate schedule id: {schedule_id}")
        if frequency not in recurrence_keys:
            raise ConfigurationError(
                "schedules.frequency must be daily, weekly, monthly, or once"
            )
        if not isinstance(at, str) or not re.fullmatch(
            r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", at
        ):
            raise ConfigurationError("schedules.at must use a valid 24-hour HH:MM value")
        if not isinstance(enabled, bool):
            raise ConfigurationError("schedules.enabled must be a boolean")

        expected_keys = common_keys | recurrence_keys[frequency]
        unexpected = set(value) - expected_keys
        if unexpected:
            raise ConfigurationError(
                "schedules has unexpected fields for "
                f"{frequency}: {', '.join(sorted(unexpected))}"
            )
        missing = recurrence_keys[frequency] - set(value)
        if missing:
            raise ConfigurationError(
                f"schedules.{next(iter(missing))} is required for {frequency}"
            )

        days: tuple[str, ...] = ()
        day_value: int | None = None
        date_value: str | None = None
        if frequency == "weekly":
            raw_days = value["days"]
            if not isinstance(raw_days, list) or not raw_days or any(
                not isinstance(item, str)
                or item.casefold() not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
                for item in raw_days
            ):
                raise ConfigurationError(
                    "schedules.days must be a non-empty array of weekday names"
                )
            days = tuple(item.casefold() for item in raw_days)
            if len(set(days)) != len(days):
                raise ConfigurationError("schedules.days must not contain duplicate weekdays")
        elif frequency == "monthly":
            raw_day = value["day"]
            if isinstance(raw_day, bool) or not isinstance(raw_day, int) or not 1 <= raw_day <= 31:
                raise ConfigurationError("schedules.day must be an integer from 1 through 31")
            day_value = raw_day
        elif frequency == "once":
            raw_date = value["date"]
            if not isinstance(raw_date, str):
                raise ConfigurationError("schedules.date must use YYYY-MM-DD")
            try:
                parsed_date = date.fromisoformat(raw_date)
            except ValueError as error:
                raise ConfigurationError("schedules.date must use a valid YYYY-MM-DD date") from error
            if parsed_date.isoformat() != raw_date:
                raise ConfigurationError("schedules.date must use YYYY-MM-DD")
            date_value = raw_date

        seen_ids.add(schedule_id)
        schedules.append(
            Schedule(schedule_id, frequency, at, enabled, days, day_value, date_value)
        )
    return tuple(schedules)
