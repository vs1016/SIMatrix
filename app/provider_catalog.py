from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import Settings

PROVIDER_CATALOG_FILENAME = "provider-catalog.json"
PROVIDER_PAGE_INDEX_CACHE_FILENAME = "provider-page-index.json"
PROVIDER_NAME_OVERRIDES = {
    "airalo": "Airalo",
    "nomad": "Nomad",
    "textr": "Textr eSIM",
    "billionconnect": "Billion Connect",
    "bytesim": "ByteSIM",
}


def provider_catalog_path(settings: Settings) -> Path:
    return settings.data_dir / PROVIDER_CATALOG_FILENAME


def provider_page_index_cache_path(settings: Settings) -> Path:
    return settings.data_dir / PROVIDER_PAGE_INDEX_CACHE_FILENAME


def provider_slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    return path.split("/")[-1].lower()


def provider_slug_from_hostname(hostname: str) -> str:
    normalized_host = hostname.strip().lower()
    if not normalized_host:
        return ""
    if normalized_host.startswith("www."):
        normalized_host = normalized_host[4:]
    host_parts = [part for part in normalized_host.split(".") if part]
    if not host_parts:
        return ""
    if len(host_parts) >= 3 and host_parts[-2] in {"co", "com", "net", "org"}:
        candidate = host_parts[-3]
    elif len(host_parts) >= 2:
        candidate = host_parts[-2]
    else:
        candidate = host_parts[0]
    candidate = re.sub(r"[^a-z0-9-]+", "-", candidate)
    return candidate.strip("-")


def humanize_provider_slug(provider_slug: str) -> str:
    normalized_slug = provider_slug.strip().lower()
    if not normalized_slug:
        return ""
    if normalized_slug in PROVIDER_NAME_OVERRIDES:
        return PROVIDER_NAME_OVERRIDES[normalized_slug]
    return normalized_slug.replace("-", " ").title()


def normalize_provider_name(raw_name: str, provider_slug: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw_name).strip()
    cleaned = re.sub(
        r"\s+eSIM Data Plans for\s+.+$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = cleaned.replace("#", "").strip()
    return cleaned or humanize_provider_slug(provider_slug)


def normalize_provider_lookup_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def normalize_hostname(hostname: str) -> str:
    normalized_host = hostname.strip().lower()
    if normalized_host.startswith("www."):
        return normalized_host[4:]
    return normalized_host


def normalize_provider_catalog_entries(
    entries: list[dict[str, str]],
) -> list[dict[str, str]]:
    normalized_entries: dict[str, dict[str, str]] = {}
    for entry in entries:
        provider_slug = str(entry.get("provider_slug", "")).strip().lower()
        if not provider_slug:
            continue
        provider_name = normalize_provider_name(
            str(entry.get("provider_name", "")).strip(),
            provider_slug,
        )
        normalized_entries[provider_slug] = {
            "provider_slug": provider_slug,
            "provider_name": provider_name,
            "website_url": str(entry.get("website_url", "")).strip(),
            "official_website_url": str(entry.get("official_website_url", "")).strip(),
            "added_at": str(entry.get("added_at", "")).strip()
            or datetime.now(UTC).isoformat(timespec="seconds"),
        }
    return sorted(
        normalized_entries.values(),
        key=lambda item: (item["provider_name"].lower(), item["provider_slug"]),
    )


def build_default_provider_catalog(settings: Settings) -> list[dict[str, str]]:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    return normalize_provider_catalog_entries(
        [
            {
                "provider_slug": provider_slug,
                "provider_name": humanize_provider_slug(provider_slug),
                "website_url": "",
                "official_website_url": "",
                "added_at": timestamp,
            }
            for provider_slug in settings.preset_provider_slugs
        ]
    )


def load_provider_catalog(settings: Settings) -> list[dict[str, str]]:
    catalog_path = provider_catalog_path(settings)
    if not catalog_path.exists():
        catalog = build_default_provider_catalog(settings)
        save_provider_catalog(settings, catalog)
        return catalog

    try:
        raw_entries = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        catalog = build_default_provider_catalog(settings)
        save_provider_catalog(settings, catalog)
        return catalog

    if not isinstance(raw_entries, list):
        catalog = build_default_provider_catalog(settings)
        save_provider_catalog(settings, catalog)
        return catalog

    normalized_entries = normalize_provider_catalog_entries(
        [entry for entry in raw_entries if isinstance(entry, dict)]
    )
    return normalized_entries


def save_provider_catalog(settings: Settings, entries: list[dict[str, str]]) -> None:
    normalized_entries = normalize_provider_catalog_entries(entries)
    provider_catalog_path(settings).write_text(
        json.dumps(normalized_entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def resolve_active_provider_slugs(settings: Settings) -> tuple[str, ...]:
    catalog = load_provider_catalog(settings)
    return tuple(entry["provider_slug"] for entry in catalog if entry["provider_slug"])


def extract_provider_page_index_from_sitemap(
    sitemap_xml: str,
    base_url: str,
) -> dict[str, str]:
    canonical_host = urlparse(base_url).netloc.lower()
    provider_page_index: dict[str, str] = {}
    for loc in re.findall(r"<loc>(.*?)</loc>", sitemap_xml):
        parsed = urlparse(loc.strip())
        if parsed.netloc.lower() != canonical_host:
            continue
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) != 2:
            continue
        provider_slug = segments[1].strip().lower()
        if not provider_slug or provider_slug in provider_page_index:
            continue
        provider_page_index[provider_slug] = loc.strip()
    return provider_page_index


def load_provider_page_index_cache(settings: Settings) -> dict[str, str]:
    cache_path = provider_page_index_cache_path(settings)
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(provider_slug).strip().lower(): str(provider_url).strip()
        for provider_slug, provider_url in payload.items()
        if str(provider_slug).strip() and str(provider_url).strip()
    }


def save_provider_page_index_cache(
    settings: Settings,
    provider_page_index: dict[str, str],
) -> None:
    provider_page_index_cache_path(settings).write_text(
        json.dumps(provider_page_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_provider_page_index(settings: Settings) -> dict[str, str]:
    sitemap_url = f"{settings.base_url}/en/sitemap.xml"
    try:
        sitemap_xml = fetch_remote_html(settings, sitemap_url)
        provider_page_index = extract_provider_page_index_from_sitemap(
            sitemap_xml,
            settings.base_url,
        )
        if provider_page_index:
            save_provider_page_index_cache(settings, provider_page_index)
            return provider_page_index
    except httpx.HTTPError:
        pass
    return load_provider_page_index_cache(settings)


def extract_provider_logo_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for image in soup.find_all("img", src=True):
        src = image.get("src", "").strip()
        if "/assets/pictures/provider/" in src:
            return urljoin(base_url + "/", src.lstrip("/"))

    for image_selector in (
        {"property": "og:image"},
        {"name": "twitter:image"},
    ):
        image_meta = soup.find("meta", attrs=image_selector)
        if image_meta is not None and image_meta.get("content", "").strip():
            return urljoin(base_url + "/", image_meta["content"].strip())

    for rel_value in ("icon", "shortcut icon", "apple-touch-icon"):
        icon_link = soup.find("link", rel=lambda value: value and rel_value in str(value).lower(), href=True)
        if icon_link is not None:
            href = icon_link.get("href", "").strip()
            if href:
                return urljoin(base_url + "/", href)
    return None


def extract_provider_name(html: str, provider_slug: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for meta_selector in (
        {"property": "og:site_name"},
        {"name": "application-name"},
    ):
        meta_tag = soup.find("meta", attrs=meta_selector)
        if meta_tag is not None and meta_tag.get("content", "").strip():
            return normalize_provider_name(meta_tag["content"], provider_slug)

    heading = soup.find("h1") or soup.find("h2")
    if heading is not None:
        return normalize_provider_name(heading.get_text(" ", strip=True), provider_slug)

    for image in soup.find_all("img", alt=True):
        alt = image.get("alt", "").strip()
        if not alt or alt.lower() == "esimdb logo":
            continue
        if "/assets/pictures/provider/" in image.get("src", ""):
            return normalize_provider_name(alt, provider_slug)

    title = soup.find("title")
    if title is not None:
        return normalize_provider_name(title.get_text(" ", strip=True), provider_slug)

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title is not None and og_title.get("content", "").strip():
        return normalize_provider_name(og_title["content"], provider_slug)

    return humanize_provider_slug(provider_slug)


def extract_official_website_url(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        anchor_text = anchor.get_text(" ", strip=True).lower()
        if "official website" in anchor_text:
            return urljoin(page_url, anchor.get("href", "").strip())
    return ""


def fetch_remote_html(settings: Settings, url: str) -> str:
    blocked_error: httpx.HTTPStatusError | None = None
    try:
        with httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 403:
            raise
        blocked_error = exc
    except httpx.HTTPError:
        raise

    curl_executable = shutil.which("curl.exe") or shutil.which("curl")
    if not curl_executable:
        raise blocked_error or httpx.HTTPError(f"Could not fetch {url}")

    result = subprocess.run(
        [
            curl_executable,
            "-L",
            "--silent",
            "--show-error",
            "--fail",
            "-A",
            settings.user_agent,
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise blocked_error or httpx.HTTPError(result.stderr.strip() or f"curl failed for {url}")
    return result.stdout


def build_provider_slug_candidates(
    provider_slug_candidate: str,
    provider_name: str,
    provider_page_index: dict[str, str],
) -> list[str]:
    known_provider_slugs = list(provider_page_index)
    if not known_provider_slugs:
        return []

    scored_candidates: dict[str, float] = {}

    def record(provider_slug: str, score: float) -> None:
        if provider_slug in provider_page_index:
            scored_candidates[provider_slug] = max(score, scored_candidates.get(provider_slug, 0.0))

    normalized_slug_candidate = normalize_provider_lookup_key(provider_slug_candidate)
    normalized_name = normalize_provider_lookup_key(provider_name)

    for provider_slug in known_provider_slugs:
        normalized_provider_slug = normalize_provider_lookup_key(provider_slug)
        normalized_humanized_slug = normalize_provider_lookup_key(humanize_provider_slug(provider_slug))
        if normalized_slug_candidate and normalized_provider_slug == normalized_slug_candidate:
            record(provider_slug, 1.0)
        if normalized_name and normalized_humanized_slug == normalized_name:
            record(provider_slug, 0.98)
        if normalized_name and normalized_provider_slug == normalized_name:
            record(provider_slug, 0.96)
        if normalized_slug_candidate and normalized_slug_candidate in normalized_provider_slug:
            record(provider_slug, 0.8)
        if normalized_name and normalized_name in normalized_humanized_slug:
            record(provider_slug, 0.78)

    comparison_bases = [
        value
        for value in (provider_slug_candidate.strip().lower(), provider_name.strip().lower())
        if value
    ]
    for base in comparison_bases:
        for provider_slug in difflib.get_close_matches(base, known_provider_slugs, n=12, cutoff=0.7):
            record(provider_slug, 0.72)
        slug_by_humanized_name = {
            humanize_provider_slug(provider_slug).lower(): provider_slug
            for provider_slug in known_provider_slugs
        }
        for humanized_name in difflib.get_close_matches(base, list(slug_by_humanized_name), n=12, cutoff=0.7):
            record(slug_by_humanized_name[humanized_name], 0.7)

    return [
        provider_slug
        for provider_slug, _ in sorted(
            scored_candidates.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def resolve_provider_slug_from_index(
    provider_slug_candidate: str,
    provider_name: str,
    provider_page_index: dict[str, str],
    *,
    target_website_host: str,
    settings: Settings,
) -> tuple[str, str]:
    normalized_slug_candidate = provider_slug_candidate.strip().lower()
    if normalized_slug_candidate in provider_page_index:
        return normalized_slug_candidate, provider_page_index[normalized_slug_candidate]

    candidate_slugs = build_provider_slug_candidates(
        provider_slug_candidate,
        provider_name,
        provider_page_index,
    )
    if not candidate_slugs:
        raise ValueError("Could not match this website to an eSIMDB provider yet.")

    normalized_target_host = normalize_hostname(target_website_host)
    for provider_slug in candidate_slugs[:12]:
        provider_page_url = provider_page_index[provider_slug]
        try:
            provider_page_html = fetch_remote_html(settings, provider_page_url)
        except httpx.HTTPError:
            continue
        official_website_url = extract_official_website_url(provider_page_html, provider_page_url)
        official_website_host = normalize_hostname(urlparse(official_website_url).hostname or "")
        if official_website_host and official_website_host == normalized_target_host:
            return provider_slug, provider_page_url

    for provider_slug in candidate_slugs:
        normalized_lookup_slug = normalize_provider_lookup_key(provider_slug)
        normalized_lookup_name = normalize_provider_lookup_key(humanize_provider_slug(provider_slug))
        if normalized_lookup_slug == normalize_provider_lookup_key(provider_slug_candidate):
            return provider_slug, provider_page_index[provider_slug]
        if normalized_lookup_name == normalize_provider_lookup_key(provider_name):
            return provider_slug, provider_page_index[provider_slug]

    raise ValueError("Could not match this website to an eSIMDB provider yet.")


def cache_provider_logo(
    settings: Settings,
    *,
    provider_slug: str,
    logo_url: str | None,
) -> bool:
    if not logo_url:
        return False

    existing_logo_paths = [
        path
        for path in settings.provider_icon_dir.glob(f"{provider_slug.lower()}.*")
        if path.is_file()
    ]
    if existing_logo_paths:
        return False

    suffix = Path(urlparse(logo_url).path).suffix.lower() or ".png"
    target_path = settings.provider_icon_dir / f"{provider_slug.lower()}{suffix}"
    if target_path.exists():
        return False

    try:
        with httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            response = client.get(logo_url)
            response.raise_for_status()
            target_path.write_bytes(response.content)
    except httpx.HTTPError:
        return False
    return True


def register_provider_from_url(settings: Settings, website_url: str) -> dict[str, str]:
    normalized_url = website_url.strip()
    if not normalized_url:
        raise ValueError("Provider website URL is required.")

    parsed_url = urlparse(normalized_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Please enter a valid provider website URL.")

    expected_host = urlparse(settings.base_url).netloc.lower()
    is_esimdb_provider_page = parsed_url.netloc.lower() == expected_host
    path_segments = [segment for segment in parsed_url.path.split("/") if segment]
    if is_esimdb_provider_page and len(path_segments) < 2:
        raise ValueError("Use an eSIMDB provider page URL like https://esimdb.com/usa/airalo.")

    provider_slug = (
        provider_slug_from_url(normalized_url)
        if is_esimdb_provider_page
        else provider_slug_from_hostname(parsed_url.hostname or "")
    )
    if not provider_slug:
        raise ValueError("Could not determine the provider slug from that URL.")

    html = fetch_remote_html(settings, normalized_url)

    provider_name = extract_provider_name(html, provider_slug)
    logo_url = extract_provider_logo_url(html, normalized_url)
    official_website_url = extract_official_website_url(html, normalized_url)

    if is_esimdb_provider_page:
        resolved_provider_slug = provider_slug
        resolved_provider_page_url = normalized_url
        resolved_provider_html = html
    else:
        provider_page_index = load_provider_page_index(settings)
        resolved_provider_slug, resolved_provider_page_url = resolve_provider_slug_from_index(
            provider_slug,
            provider_name,
            provider_page_index,
            target_website_host=parsed_url.hostname or "",
            settings=settings,
        )
        resolved_provider_html = fetch_remote_html(settings, resolved_provider_page_url)
        provider_name = extract_provider_name(resolved_provider_html, resolved_provider_slug)
        logo_url = extract_provider_logo_url(resolved_provider_html, settings.base_url) or logo_url
        official_website_url = (
            extract_official_website_url(resolved_provider_html, resolved_provider_page_url)
            or normalized_url
        )

    cache_provider_logo(
        settings,
        provider_slug=resolved_provider_slug,
        logo_url=logo_url,
    )
    return {
        "provider_slug": resolved_provider_slug,
        "provider_name": provider_name,
        "website_url": normalized_url,
        "official_website_url": official_website_url or normalized_url,
        "added_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
