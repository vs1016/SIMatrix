from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_url: str
    project_root: Path
    data_dir: Path
    database_path: Path
    flag_icon_dir: Path
    provider_icon_dir: Path
    supported_destinations: tuple[str, ...]
    preset_provider_slugs: tuple[str, ...]
    destination_match_mode: str
    max_providers_per_destination: int | None
    provider_fetch_workers: int
    http_timeout_seconds: float
    user_agent: str

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.provider_icon_dir.mkdir(parents=True, exist_ok=True)


def _parse_supported_destinations(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return ("usa",)
    return tuple(part.strip().lower() for part in raw_value.split(",") if part.strip())


def _parse_provider_slugs(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return (
            "airalo",
            "nomad",
            "textr",
            "billionconnect",
            "bytesim",
        )
    return tuple(part.strip().lower() for part in raw_value.split(",") if part.strip())


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value in (None, ""):
        return None
    return int(raw_value)


def _parse_positive_int(raw_value: str | None, *, default: int) -> int:
    if raw_value in (None, ""):
        return default
    return max(1, int(raw_value))


def _parse_destination_match_mode(raw_value: str | None) -> str:
    if raw_value in {"strict", "relaxed"}:
        return raw_value
    return "strict"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.getenv("ESIMDB_DATA_DIR", str(project_root / "data")))
    database_path = Path(
        os.getenv("ESIMDB_DATABASE_PATH", str(data_dir / "esimdb.sqlite3"))
    )
    return Settings(
        base_url=os.getenv("ESIMDB_BASE_URL", "https://esimdb.com").rstrip("/"),
        project_root=project_root,
        data_dir=data_dir,
        database_path=database_path,
        flag_icon_dir=project_root / "icon",
        provider_icon_dir=data_dir / "provider-icons",
        supported_destinations=_parse_supported_destinations(
            os.getenv("ESIMDB_SUPPORTED_DESTINATIONS")
        ),
        preset_provider_slugs=_parse_provider_slugs(
            os.getenv("ESIMDB_PRESET_PROVIDER_SLUGS")
        ),
        destination_match_mode=_parse_destination_match_mode(
            os.getenv("ESIMDB_DESTINATION_MATCH_MODE")
        ),
        max_providers_per_destination=_parse_optional_int(
            os.getenv("ESIMDB_MAX_PROVIDERS_PER_DESTINATION")
        ),
        provider_fetch_workers=_parse_positive_int(
            os.getenv("ESIMDB_PROVIDER_FETCH_WORKERS"),
            default=6,
        ),
        http_timeout_seconds=float(os.getenv("ESIMDB_HTTP_TIMEOUT", "20")),
        user_agent=os.getenv(
            "ESIMDB_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 RTG-Local-Scraper/1.0",
        ),
    )
