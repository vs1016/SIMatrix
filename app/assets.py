from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico")
DESTINATION_ICON_ALIASES = {
    "usa": ("united states", "united states of america", "usa"),
    "uk": ("united kingdom", "great britain", "uk"),
    "uae": ("united arab emirates", "uae"),
}


def normalize_icon_name(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    cleaned = cleaned.replace("-", " ")
    cleaned = cleaned.replace("_", " ")
    return cleaned


def find_matching_icon_path(icon_dir: Path, candidates: list[str]) -> Path | None:
    if not icon_dir.exists():
        return None

    normalized_candidates = {normalize_icon_name(candidate) for candidate in candidates if candidate}
    for path in icon_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stem = normalize_icon_name(path.stem)
        if stem in normalized_candidates:
            return path
    return None


def resolve_destination_icon_url(settings: Settings, destination_slug: str, destination_name: str) -> str | None:
    candidates = [destination_name, destination_slug]
    candidates.extend(DESTINATION_ICON_ALIASES.get(destination_slug.lower(), ()))
    path = find_matching_icon_path(settings.flag_icon_dir, candidates)
    if path is None:
        return None
    return f"/flags/{path.name}"


def resolve_provider_icon_url(settings: Settings, provider_slug: str) -> str | None:
    path = find_matching_icon_path(settings.provider_icon_dir, [provider_slug])
    if path is None:
        return None
    return f"/provider-icons/{path.name}"
