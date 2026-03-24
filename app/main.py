from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import json
import re
from threading import Lock, Thread
from typing import Iterator
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.assets import resolve_destination_icon_url, resolve_provider_icon_url
from app.config import Settings, get_settings
from app.database import connect_database, initialize_database
from app.models import PlanFilters
from app.provider_catalog import (
    load_provider_catalog,
    normalize_provider_catalog_entries,
    register_provider_from_url,
    resolve_active_provider_slugs,
    save_provider_catalog,
)
from app.repository import Repository
from app.scraper import EsimDbScraperService

DESTINATION_CATALOG_CACHE_FILENAME = "destination-catalog.json"
DESTINATION_CATALOG_REFRESH_INTERVAL = timedelta(hours=12)

TRANSLATIONS = {
    "en": {
        "page_title": "SIMatrix",
        "hero_title_line_1": "A local-first pipeline",
        "hero_title_line_2_prefix": "for",
        "hero_title_highlight": "eSIMDB",
        "hero_title_line_2_suffix": "data",
        "hero_title_line_3": "extraction and curation.",
        "hero_lede": "This dashboard unifies scraped data, enables intuitive exploration, and outputs curated datasets as CSV.",
        "select_destinations": "Select destinations",
        "search_destinations": "Search destinations",
        "destination_picker_prefix": "Find your destination in",
        "destination_picker_suffix": "countries.",
        "destination_picker_placeholder": 'Find your destination in "{count}" countries.',
        "get_started": "Get Started",
        "docs": "More",
        "no_destination_results": "No matching destinations",
        "match_mode": "Match mode",
        "match_mode_help": "How destination matching works",
        "strict_mode": "Strict",
        "strict_mode_help": "Only keep plans that explicitly match the selected destination.",
        "relaxed_mode": "Relaxed",
        "relaxed_mode_help": "Also keep plans that may apply to the destination even if naming is broader.",
        "download_csv": "Download CSV",
        "destination": "Destination",
        "all_destinations": "All destinations",
        "provider": "Provider",
        "all_providers": "All providers",
        "min_price": "Min price (USD)",
        "max_price": "Max price (USD)",
        "min_validity": "Min validity (days)",
        "min_data": "Min data (GB)",
        "apply_filters": "Apply Filters",
        "reset": "Reset",
        "plan": "Plan",
        "data": "Data",
        "validity": "Validity",
        "price": "Price",
        "price_per_gb": "Price/GB",
        "source": "Source",
        "open": "Open",
        "days_suffix": "days",
        "no_plans_title": "No plans match the current view.",
        "no_plans_body": "Run a scrape or relax your filters to see exportable records here.",
        "language_zh": "\u4e2d\u6587",
        "language_en": "EN",
        "loading_title": "Scraping in progress",
        "loading_body": "Fetching provider pages and refreshing local data. This page will update when the scrape finishes.",
        "scrape_complete": "Scrape complete. Inserted {inserted}, updated {updated}, skipped {skipped}.",
        "scrape_failed": "Scrape failed: {error}",
        "docs_page_title": "Provider Registry",
        "docs_heading": "Manage active providers",
        "docs_lede": "Paste a provider website like https://bytesim.com. SIMatrix will parse the slug, display name, and logo automatically, then keep the provider in the local registry for future scrapes.",
        "docs_form_title": "Add provider",
        "docs_form_body": "Use a provider website URL like https://bytesim.com or an eSIMDB provider page URL.",
        "docs_url_label": "Provider website URL",
        "docs_url_placeholder": "https://bytesim.com",
        "docs_add_provider": "Add Provider",
        "docs_manage_hint": "These providers define the active whitelist for future scrapes.",
        "docs_provider_count": "{count} providers currently active",
        "docs_table_provider": "Provider",
        "docs_table_slug": "Slug",
        "docs_table_source": "Source page",
        "docs_table_website": "Official website",
        "docs_table_added": "Added",
        "docs_table_actions": "Actions",
        "docs_delete": "Delete",
        "docs_empty_title": "No providers have been added yet.",
        "docs_empty_body": "Add an eSIMDB provider page URL to build your local provider registry.",
        "docs_api_docs": "API Docs",
        "docs_back_home": "Back to dashboard",
        "docs_add_success": "{name} has been added.",
        "docs_update_success": "{name} has been updated.",
        "docs_delete_success": "{name} has been removed.",
        "docs_delete_missing": "Provider not found.",
        "docs_submit_loading": "Parsing...",
    },
    "zh": {
        "page_title": "SIMatrix",
        "hero_title_line_1": "\u4e00\u6761\u672c\u5730\u4f18\u5148\u7684",
        "hero_title_line_2_prefix": "",
        "hero_title_highlight": "eSIMDB",
        "hero_title_line_2_suffix": "\u6570\u636e\u7ba1\u7ebf",
        "hero_title_line_3": "\u91c7\u96c6\u4e0e\u6574\u7406",
        "hero_lede": "\u8fd9\u4e2a\u4eea\u8868\u76d8\u4f1a\u7edf\u4e00\u6293\u53d6\u7ed3\u679c\uff0c\u652f\u6301\u76f4\u89c2\u7b5b\u9009\uff0c\u5e76\u5c06\u6574\u7406\u540e\u7684\u6570\u636e\u5bfc\u51fa\u4e3a CSV\u3002",
        "select_destinations": "\u9009\u62e9\u56fd\u5bb6",
        "search_destinations": "\u641c\u7d22\u56fd\u5bb6",
        "destination_picker_prefix": "\u5728",
        "destination_picker_suffix": "\u4e2a\u56fd\u5bb6\u4e2d\u67e5\u627e\u4f60\u7684\u76ee\u7684\u5730\u3002",
        "destination_picker_placeholder": '\u5728"{count}"\u4e2a\u56fd\u5bb6\u4e2d\u67e5\u627e\u4f60\u7684\u76ee\u7684\u5730\u3002',
        "get_started": "\u5f00\u59cb\u6293\u53d6",
        "docs": "\u66f4\u591a",
        "no_destination_results": "\u6ca1\u6709\u5339\u914d\u7684\u56fd\u5bb6",
        "match_mode": "\u5339\u914d\u6a21\u5f0f",
        "match_mode_help": "\u76ee\u7684\u5730\u5339\u914d\u89c4\u5219\u8bf4\u660e",
        "strict_mode": "\u4e25\u683c",
        "strict_mode_help": "\u53ea\u4fdd\u7559\u540d\u79f0\u4e2d\u660e\u786e\u5339\u914d\u6240\u9009\u56fd\u5bb6\u7684\u5957\u9910\u3002",
        "relaxed_mode": "\u5bbd\u677e",
        "relaxed_mode_help": "\u4f1a\u989d\u5916\u4fdd\u7559\u90a3\u4e9b\u53ef\u80fd\u9002\u7528\u4e8e\u8be5\u56fd\u5bb6\uff0c\u4f46\u547d\u540d\u66f4\u7b3c\u7edf\u7684\u5957\u9910\u3002",
        "download_csv": "\u4e0b\u8f7d CSV",
        "destination": "\u56fd\u5bb6",
        "all_destinations": "\u5168\u90e8\u56fd\u5bb6",
        "provider": "\u4f9b\u5e94\u5546",
        "all_providers": "\u5168\u90e8\u4f9b\u5e94\u5546",
        "min_price": "\u6700\u4f4e\u4ef7\u683c (USD)",
        "max_price": "\u6700\u9ad8\u4ef7\u683c (USD)",
        "min_validity": "\u6700\u77ed\u6709\u6548\u671f (\u5929)",
        "min_data": "\u6700\u5c0f\u6d41\u91cf (GB)",
        "apply_filters": "\u5e94\u7528\u7b5b\u9009",
        "reset": "\u91cd\u7f6e",
        "plan": "\u5957\u9910",
        "data": "\u6d41\u91cf",
        "validity": "\u6709\u6548\u671f",
        "price": "\u4ef7\u683c",
        "price_per_gb": "\u6bcf GB \u4ef7\u683c",
        "source": "\u6765\u6e90",
        "open": "\u6253\u5f00",
        "days_suffix": "\u5929",
        "no_plans_title": "\u5f53\u524d\u89c6\u56fe\u6ca1\u6709\u5339\u914d\u7684\u5957\u9910\u3002",
        "no_plans_body": "\u8bf7\u5148\u8fd0\u884c\u6293\u53d6\uff0c\u6216\u653e\u5bbd\u7b5b\u9009\u6761\u4ef6\u540e\u518d\u67e5\u770b\u3002",
        "language_zh": "\u4e2d\u6587",
        "language_en": "EN",
        "loading_title": "\u6b63\u5728\u6293\u53d6",
        "loading_body": "\u6b63\u5728\u6293\u53d6\u4f9b\u5e94\u5546\u9875\u9762\u5e76\u5237\u65b0\u672c\u5730\u6570\u636e\u3002\u6293\u53d6\u5b8c\u6210\u540e\u9875\u9762\u4f1a\u81ea\u52a8\u66f4\u65b0\u3002",
        "scrape_complete": "\u6293\u53d6\u5b8c\u6210\u3002\u65b0\u589e {inserted}\uff0c\u66f4\u65b0 {updated}\uff0c\u8df3\u8fc7 {skipped}\u3002",
        "scrape_failed": "\u6293\u53d6\u5931\u8d25\uff1a{error}",
        "docs_page_title": "\u8fd0\u8425\u5546\u7ba1\u7406",
        "docs_heading": "\u7ba1\u7406\u5f53\u524d\u542f\u7528\u7684\u8fd0\u8425\u5546",
        "docs_lede": "\u7c98\u8d34\u8fd0\u8425\u5546\u7f51\u7ad9 URL\uff0c\u4f8b\u5982 https://bytesim.com\u3002SIMatrix \u4f1a\u81ea\u52a8\u89e3\u6790 slug\u3001\u663e\u793a\u540d\u79f0\u548c logo\uff0c\u5e76\u5c06\u5176\u4fdd\u5b58\u5230\u672c\u5730\u8fd0\u8425\u5546\u5217\u8868\u91cc\uff0c\u4f9b\u540e\u7eed\u6293\u53d6\u4f7f\u7528\u3002",
        "docs_form_title": "\u65b0\u589e\u8fd0\u8425\u5546",
        "docs_form_body": "\u8bf7\u8f93\u5165\u8fd0\u8425\u5546\u7f51\u7ad9 URL\uff0c\u4f8b\u5982 https://bytesim.com\uff0c\u4e5f\u652f\u6301 eSIMDB \u7684 provider \u9875\u9762 URL\u3002",
        "docs_url_label": "\u8fd0\u8425\u5546\u7f51\u7ad9 URL",
        "docs_url_placeholder": "https://bytesim.com",
        "docs_add_provider": "\u6dfb\u52a0\u8fd0\u8425\u5546",
        "docs_manage_hint": "\u8fd9\u4e9b\u8fd0\u8425\u5546\u4f1a\u7ec4\u6210\u540e\u7eed\u6293\u53d6\u7684\u6709\u6548\u767d\u540d\u5355\u3002",
        "docs_provider_count": "\u5f53\u524d\u5171\u542f\u7528 {count} \u4e2a\u8fd0\u8425\u5546",
        "docs_table_provider": "\u8fd0\u8425\u5546",
        "docs_table_slug": "Slug",
        "docs_table_source": "\u89e3\u6790\u6765\u6e90\u9875",
        "docs_table_website": "\u5b98\u65b9\u7f51\u7ad9",
        "docs_table_added": "\u6dfb\u52a0\u65f6\u95f4",
        "docs_table_actions": "\u64cd\u4f5c",
        "docs_delete": "\u5220\u9664",
        "docs_empty_title": "\u8fd8\u6ca1\u6709\u6dfb\u52a0\u8fd0\u8425\u5546\u3002",
        "docs_empty_body": "\u5148\u6dfb\u52a0\u4e00\u4e2a eSIMDB \u8fd0\u8425\u5546\u9875\u9762 URL\uff0c\u672c\u5730 provider registry \u5c31\u4f1a\u5efa\u8d77\u6765\u3002",
        "docs_api_docs": "API \u6587\u6863",
        "docs_back_home": "\u8fd4\u56de\u9996\u9875",
        "docs_add_success": "\u5df2\u6dfb\u52a0 {name}\u3002",
        "docs_update_success": "\u5df2\u66f4\u65b0 {name}\u3002",
        "docs_delete_success": "\u5df2\u79fb\u9664 {name}\u3002",
        "docs_delete_missing": "\u8fd0\u8425\u5546\u4e0d\u5b58\u5728\u3002",
        "docs_submit_loading": "\u6b63\u5728\u89e3\u6790...",
    },
}

def parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def resolve_language(raw_lang: str | None) -> str:
    return raw_lang if raw_lang in TRANSLATIONS else "en"


def build_filters(
    destination_slug: str = "",
    provider_slug: str = "",
    min_price: str | None = None,
    max_price: str | None = None,
    min_validity_days: str | None = None,
    min_data_gb: str | None = None,
    sort_by: str = "price_amount",
    sort_order: str = "asc",
) -> PlanFilters:
    min_data_mb = None
    if min_data_gb not in (None, ""):
        min_data_mb = float(min_data_gb) * 1024
    return PlanFilters(
        destination_slug=destination_slug,
        provider_slug=provider_slug,
        min_price=parse_float(min_price),
        max_price=parse_float(max_price),
        min_validity_days=parse_int(min_validity_days),
        min_data_mb=min_data_mb,
        sort_by=sort_by,
        sort_order=sort_order if sort_order in {"asc", "desc"} else "asc",
    )


def calculate_average_price_per_gb(plans) -> float | None:
    values = [
        float(plan["price_per_gb"])
        for plan in plans
        if plan["price_per_gb"] is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def normalize_destination_display_name(slug: str, name: str) -> str:
    normalized_slug = slug.strip().lower()
    raw_name = re.sub(r"\s+", " ", name).strip()
    raw_name = re.sub(r"^(?:[\U0001F1E6-\U0001F1FF]{2}\s*)+", "", raw_name).strip()
    cleaned_name = raw_name
    if not cleaned_name:
        return normalized_slug.replace("-", " ").title()

    slug_prefix = normalized_slug.replace("-", " ")
    upper_prefix = normalized_slug.upper()
    cleaned_name = re.sub(
        rf"^(?:{re.escape(upper_prefix)}|{re.escape(slug_prefix)})\s+",
        "",
        cleaned_name,
        flags=re.IGNORECASE,
    ).strip()
    slug_parts = [part for part in normalized_slug.split("-") if part]
    slug_initials = "".join(part[:1] for part in slug_parts).lower()
    leading_token_match = re.match(r"^([A-Za-z]{2,3})\s+(.+)$", cleaned_name)
    if leading_token_match:
        leading_token = leading_token_match.group(1).lower()
        remainder = leading_token_match.group(2).strip()
        comparable_slug = normalized_slug.replace("-", "")
        if (
            leading_token == comparable_slug
            or leading_token == normalized_slug
            or leading_token == slug_initials
            or comparable_slug.startswith(leading_token)
        ):
            cleaned_name = remainder
    code_match = re.match(r"^\s*([A-Za-z]{2,3})\s+(?=[A-Z][a-z])", raw_name)
    if code_match:
        cleaned_name = re.sub(
            rf"^{re.escape(code_match.group(1))}\s+",
            "",
            cleaned_name,
            flags=re.IGNORECASE,
        ).strip()
    cleaned_name = re.sub(r"^[A-Z]{2,3}\s+(?=[A-Z][a-z])", "", cleaned_name).strip()
    return cleaned_name or normalized_slug.replace("-", " ").title()


def resolve_destination_display_code(slug: str, raw_name: str) -> str:
    normalized_slug = slug.strip().lower()
    code_match = re.match(r"^\s*([A-Za-z]{2,3})\s+(?=[A-Z][a-z])", raw_name.strip())
    if code_match:
        return code_match.group(1).upper()
    return resolve_destination_short_label(normalized_slug)


def build_destination_option(
    slug: str,
    raw_name: str,
    *,
    settings: Settings,
) -> dict[str, str | float | None]:
    normalized_slug = slug.strip().lower()
    destination_name = normalize_destination_display_name(normalized_slug, raw_name.strip())
    map_x, map_y = resolve_destination_map_position(normalized_slug)
    return {
        "slug": normalized_slug,
        "name": destination_name,
        "short_label": resolve_destination_display_code(normalized_slug, raw_name),
        "map_x": map_x,
        "map_y": map_y,
        "icon_url": resolve_destination_icon_url(
            settings,
            normalized_slug,
            destination_name,
        ),
    }


def build_destination_picker_groups(
    options: list[dict[str, str | float | None]],
) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, str | float | None]]] = {}
    for option in options:
        name = str(option.get("name") or "").strip()
        letter = name[:1].upper() if name else "#"
        if not letter.isalpha():
            letter = "#"
        groups.setdefault(letter, []).append(option)

    return [
        {
            "letter": letter,
            "items": sorted(items, key=lambda item: str(item["name"]).lower()),
        }
        for letter, items in sorted(groups.items(), key=lambda item: item[0])
    ]


def destination_catalog_cache_path(settings: Settings):
    return settings.data_dir / DESTINATION_CATALOG_CACHE_FILENAME


def merge_destination_options(
    primary: list[dict[str, str | float | None]],
    fallback: list[dict[str, str | float | None]],
) -> list[dict[str, str | float | None]]:
    merged = list(primary)
    known_slugs = {str(item["slug"]) for item in merged}
    for item in fallback:
        slug = str(item["slug"])
        if slug not in known_slugs:
            merged.append(item)
    merged.sort(key=lambda item: str(item["name"]).lower())
    return merged


def normalize_remote_destination_options(
    remote_items: list[dict[str, str]],
    *,
    settings: Settings,
) -> list[dict[str, str | float | None]]:
    options: list[dict[str, str | float | None]] = []
    for item in remote_items:
        slug = str(item.get("slug", "")).strip().lower()
        raw_name = str(item.get("name", "")).strip()
        if not slug or not raw_name:
            continue
        destination_option = build_destination_option(
            slug,
            raw_name,
            settings=settings,
        )
        if not destination_option["icon_url"]:
            continue
        options.append(destination_option)
    options.sort(key=lambda item: str(item["name"]).lower())
    return options


def load_destination_catalog_cache(
    settings: Settings,
) -> tuple[list[dict[str, str | float | None]] | None, datetime | None]:
    cache_path = destination_catalog_cache_path(settings)
    if not cache_path.exists():
        return None, None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None

    raw_items = payload.get("items", []) if isinstance(payload, dict) else payload
    refreshed_at_text = payload.get("refreshed_at") if isinstance(payload, dict) else None
    refreshed_at = None
    if isinstance(refreshed_at_text, str):
        try:
            refreshed_at = datetime.fromisoformat(refreshed_at_text)
        except ValueError:
            refreshed_at = None

    if not isinstance(raw_items, list):
        return None, refreshed_at

    options = normalize_remote_destination_options(raw_items, settings=settings)
    return (options or None), refreshed_at


def save_destination_catalog_cache(
    settings: Settings,
    options: list[dict[str, str | float | None]],
) -> None:
    cache_path = destination_catalog_cache_path(settings)
    payload = {
        "refreshed_at": datetime.now(UTC).isoformat(),
        "items": [
            {
                "slug": str(item["slug"]),
                "name": str(item["name"]),
            }
            for item in options
        ],
    }
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def format_provider_added_at(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def serialize_provider_catalog(
    provider_catalog: list[dict[str, str]],
    *,
    settings: Settings,
) -> list[dict[str, str]]:
    return [
        {
            **provider,
            "icon_url": resolve_provider_icon_url(settings, provider["provider_slug"]) or "",
            "added_at_display": format_provider_added_at(provider.get("added_at", "")),
        }
        for provider in provider_catalog
    ]


DESTINATION_MAP_POINTS: dict[str, tuple[float, float]] = {
    "es": (45.5, 35.4),
    "fr": (49.8, 31.8),
    "it": (54.3, 37.8),
    "ja": (88.6, 35.1),
    "region": (52.0, 40.0),
    "usa": (20.8, 36.2),
    "canada": (22.4, 23.0),
    "mexico": (16.8, 48.4),
    "brazil": (33.6, 68.4),
    "argentina": (29.7, 84.6),
    "chile": (25.6, 82.8),
    "colombia": (23.8, 57.0),
    "peru": (26.0, 67.4),
    "uk": (48.6, 24.2),
    "ireland": (46.1, 24.8),
    "france": (49.6, 31.8),
    "spain": (46.0, 35.5),
    "portugal": (44.0, 36.2),
    "germany": (52.6, 27.9),
    "russia": (74.0, 22.0),
    "netherlands": (50.2, 26.6),
    "belgium": (49.9, 29.0),
    "switzerland": (51.8, 33.0),
    "austria": (54.0, 31.6),
    "italy": (54.2, 37.9),
    "poland": (56.8, 28.6),
    "sweden": (55.9, 18.0),
    "norway": (52.2, 14.0),
    "finland": (60.3, 16.8),
    "denmark": (52.6, 22.4),
    "turkey": (61.2, 36.8),
    "egypt": (57.9, 46.2),
    "morocco": (44.8, 43.5),
    "algeria": (48.2, 44.5),
    "tunisia": (53.8, 41.8),
    "ivory-coast": (47.0, 56.2),
    "south-africa": (57.8, 82.4),
    "botswana": (58.7, 75.5),
    "mozambique": (61.7, 74.0),
    "zimbabwe": (58.8, 72.0),
    "nigeria": (50.0, 56.5),
    "kenya": (60.8, 61.4),
    "uae": (67.5, 44.9),
    "saudi-arabia": (64.0, 46.6),
    "qatar": (67.8, 46.1),
    "iran": (67.2, 39.5),
    "india": (72.6, 49.6),
    "pakistan": (69.2, 44.8),
    "china": (79.8, 38.3),
    "hong-kong": (83.1, 45.8),
    "macau": (82.4, 46.2),
    "taiwan": (84.8, 45.2),
    "japan": (88.6, 35.1),
    "south-korea": (85.7, 34.2),
    "thailand": (79.1, 53.0),
    "vietnam": (82.3, 51.6),
    "malaysia": (80.8, 60.6),
    "singapore": (81.4, 63.3),
    "indonesia": (85.1, 66.9),
    "philippines": (88.3, 54.5),
    "australia": (89.4, 78.6),
    "new-zealand": (96.4, 86.1),
    "bahamas": (24.8, 42.2),
    "barbados": (32.5, 58.0),
    "bermuda": (28.8, 31.5),
    "aruba": (25.4, 56.9),
    "cayman-islands": (20.8, 50.4),
    "costa-rica": (17.0, 54.6),
    "cuba": (21.4, 45.6),
    "dominican-republic": (24.5, 49.2),
    "guadeloupe": (29.6, 52.0),
    "guatemala": (16.0, 52.4),
    "guam": (92.2, 54.8),
    "jamaica": (21.6, 49.8),
    "martinique": (30.1, 53.8),
    "nicaragua": (16.2, 56.0),
    "panama": (18.7, 57.2),
    "puerto-rico": (25.7, 50.1),
    "saint-pierre-and-miquelon": (28.0, 29.0),
    "samoa": (95.2, 67.4),
    "fiji": (94.2, 69.8),
    "french-polynesia": (8.8, 66.4),
    "new-caledonia": (93.8, 82.2),
    "northern-mariana-islands": (91.0, 50.5),
    "palau": (86.9, 56.9),
    "papua-new-guinea": (89.0, 69.8),
    "greenland": (35.2, 12.4),
    "uruguay": (31.4, 79.0),
    "peru": (26.0, 67.4),
    "colombia": (23.8, 57.0),
    "guam": (92.2, 54.8),
}

FALLBACK_MAP_POINTS: tuple[tuple[float, float], ...] = (
    (18.0, 28.0),
    (22.0, 52.0),
    (29.0, 72.0),
    (48.0, 24.0),
    (55.0, 47.0),
    (60.0, 68.0),
    (75.0, 31.0),
    (82.0, 57.0),
    (91.0, 79.0),
)


def resolve_destination_map_position(slug: str) -> tuple[float, float]:
    normalized_slug = slug.strip().lower()
    if normalized_slug in DESTINATION_MAP_POINTS:
        return DESTINATION_MAP_POINTS[normalized_slug]
    seed = sum(ord(char) for char in normalized_slug)
    return FALLBACK_MAP_POINTS[seed % len(FALLBACK_MAP_POINTS)]


def resolve_destination_short_label(slug: str) -> str:
    normalized_slug = slug.strip().lower()
    special_labels = {
        "usa": "USA",
        "uk": "UK",
        "uae": "UAE",
    }
    if normalized_slug in special_labels:
        return special_labels[normalized_slug]
    if "-" in normalized_slug:
        return "".join(part[:1] for part in normalized_slug.split("-") if part)[:3].upper()
    if len(normalized_slug) <= 3:
        return normalized_slug.upper()
    return normalized_slug[:2].upper()


def describe_price_per_gb_delta(price_per_gb: float | None, average_price_per_gb: float | None) -> dict[str, float | str] | None:
    if price_per_gb is None or average_price_per_gb in (None, 0):
        return None
    delta_ratio = (float(price_per_gb) - float(average_price_per_gb)) / float(average_price_per_gb)
    if abs(delta_ratio) < 0.005:
        return {
            "label": "0%",
            "tone": "neutral",
            "value": 0.0,
        }
    return {
        "label": f"{delta_ratio:+.0%}",
        "tone": "over" if delta_ratio > 0 else "under",
        "value": delta_ratio,
    }


def build_sort_link(request: Request, filters: PlanFilters, column: str, lang: str) -> str:
    next_order = "asc"
    if filters.sort_by == column and filters.sort_order == "asc":
        next_order = "desc"
    params = {
        "lang": lang,
        "destination_slug": filters.destination_slug,
        "provider_slug": filters.provider_slug,
        "min_price": "" if filters.min_price is None else str(filters.min_price),
        "max_price": "" if filters.max_price is None else str(filters.max_price),
        "min_validity_days": "" if filters.min_validity_days is None else str(filters.min_validity_days),
        "min_data_gb": "" if filters.min_data_mb is None else str(filters.min_data_mb / 1024),
        "sort_by": column,
        "sort_order": next_order,
    }
    query = urlencode({key: value for key, value in params.items() if value != ""})
    return f"{request.url.path}?{query}"


def describe_sort_indicator(filters: PlanFilters, column: str) -> str:
    if filters.sort_by != column:
        return ""
    return "\u2191" if filters.sort_order == "asc" else "\u2193"


def normalize_export_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip()
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned or "ALL"


def build_export_filename(destination_names: list[str] | None = None) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H")
    unique_names = []
    for name in destination_names or []:
        normalized = name.strip()
        if normalized and normalized not in unique_names:
            unique_names.append(normalized)
    if not unique_names:
        destination_part = "ALL"
    elif len(unique_names) == 1:
        destination_part = normalize_export_name(unique_names[0])
    else:
        destination_part = "Multiple-Countries"
    return f"{timestamp}-{destination_part}-EsimdbExport.csv"


def create_runtime_repository(settings: Settings) -> Repository:
    connection = connect_database(settings.database_path)
    initialize_database(connection)
    return Repository(connection)


def build_fallback_destination_options(
    settings: Settings,
    repository: Repository,
) -> list[dict[str, str | None]]:
    names_by_slug: dict[str, str] = {}
    for row in repository.list_destinations():
        names_by_slug[str(row["destination_slug"])] = str(row["destination_name"])

    options: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for slug in (*settings.supported_destinations, *sorted(names_by_slug)):
        normalized_slug = slug.strip().lower()
        if not normalized_slug or normalized_slug in seen:
            continue
        seen.add(normalized_slug)
        raw_name = names_by_slug.get(
            normalized_slug,
            normalized_slug.replace("-", " ").title(),
        )
        options.append(
            build_destination_option(
                normalized_slug,
                raw_name,
                settings=settings,
            )
        )
    return options


def create_app(
    *,
    settings: Settings | None = None,
    repository: Repository | None = None,
    scraper_service: EsimDbScraperService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_settings.ensure_directories()
    connection = repository.connection if repository is not None else connect_database(
        resolved_settings.database_path
    )
    initialize_database(connection)
    resolved_repository = repository or Repository(connection)
    resolved_scraper = scraper_service or EsimDbScraperService(
        resolved_settings, resolved_repository
    )
    templates = Jinja2Templates(directory=str(resolved_settings.project_root / "app" / "templates"))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Iterator[None]:
        yield
        if repository is None:
            connection.close()

    app = FastAPI(
        title="RTG Local eSIMDB Scraper",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    app.state.settings = resolved_settings
    app.state.repository = resolved_repository
    app.state.scraper_service = resolved_scraper
    app.state.scrape_lock = Lock()
    app.state.scrape_state = {
        "running": False,
        "run_id": None,
        "error": None,
    }
    cached_destination_catalog, cached_destination_catalog_refreshed_at = load_destination_catalog_cache(
        resolved_settings
    )
    app.state.destination_catalog = cached_destination_catalog
    app.state.destination_catalog_refreshed_at = cached_destination_catalog_refreshed_at
    app.state.destination_catalog_lock = Lock()
    app.state.destination_catalog_refreshing = False
    app.state.provider_catalog_lock = Lock()
    app.state.provider_catalog = load_provider_catalog(resolved_settings)
    if hasattr(app.state.scraper_service, "refresh_active_provider_slugs"):
        app.state.scraper_service.refresh_active_provider_slugs(
            tuple(
                provider["provider_slug"]
                for provider in app.state.provider_catalog
                if provider.get("provider_slug")
            )
        )
    app.mount(
        "/static",
        StaticFiles(directory=str(resolved_settings.project_root / "app" / "static")),
        name="static",
    )
    app.mount(
        "/flags",
        StaticFiles(directory=str(resolved_settings.flag_icon_dir)),
        name="flags",
    )
    app.mount(
        "/provider-icons",
        StaticFiles(directory=str(resolved_settings.provider_icon_dir)),
        name="provider-icons",
    )

    def start_background_scrape(
        destination_slugs: list[str],
        match_mode: str,
    ) -> tuple[bool, str | None]:
        with app.state.scrape_lock:
            if app.state.scrape_state["running"]:
                return False, "already-running"

            run_id = app.state.repository.create_scrape_run(destination_slugs)
            app.state.scrape_state["running"] = True
            app.state.scrape_state["run_id"] = run_id
            app.state.scrape_state["error"] = None

        def worker() -> None:
            run_repository = app.state.repository
            run_scraper = app.state.scraper_service
            close_connection = False

            if repository is None and scraper_service is None:
                run_repository = create_runtime_repository(resolved_settings)
                run_scraper = EsimDbScraperService(resolved_settings, run_repository)
                close_connection = True

            try:
                run_repository.clear_plans()
                stats = run_scraper.scrape_destinations(
                    destination_slugs,
                    match_mode=match_mode,
                )
                run_repository.finish_scrape_run(
                    run_id,
                    status="completed",
                    inserted_count=stats.inserted_count,
                    updated_count=stats.updated_count,
                    skipped_count=stats.skipped_count,
                    error_summary=None,
                )
            except Exception as exc:
                run_repository.finish_scrape_run(
                    run_id,
                    status="failed",
                    inserted_count=0,
                    updated_count=0,
                    skipped_count=0,
                    error_summary=str(exc),
                )
                app.state.scrape_state["error"] = str(exc)
            finally:
                if close_connection:
                    run_repository.connection.close()
                with app.state.scrape_lock:
                    app.state.scrape_state["running"] = False

        if repository is not None or scraper_service is not None:
            worker()
            return True, None

        Thread(target=worker, daemon=True).start()
        return True, None

    def resolve_available_destinations() -> list[dict[str, str | None]]:
        fallback_options = build_fallback_destination_options(
            resolved_settings,
            app.state.repository,
        )

        def refresh_destination_catalog_if_needed(force: bool = False) -> None:
            if repository is not None or not hasattr(app.state.scraper_service, "list_available_destinations"):
                return

            with app.state.destination_catalog_lock:
                if app.state.destination_catalog_refreshing:
                    return
                if not force and app.state.destination_catalog_refreshed_at is not None:
                    age = datetime.now(UTC) - app.state.destination_catalog_refreshed_at
                    if age < DESTINATION_CATALOG_REFRESH_INTERVAL:
                        return
                app.state.destination_catalog_refreshing = True

            def worker() -> None:
                try:
                    remote_items = app.state.scraper_service.list_available_destinations()
                    remote_options = normalize_remote_destination_options(
                        remote_items,
                        settings=resolved_settings,
                    )
                    if not remote_options:
                        return
                    merged_options = merge_destination_options(remote_options, fallback_options)
                    refreshed_at = datetime.now(UTC)
                    with app.state.destination_catalog_lock:
                        app.state.destination_catalog = merged_options
                        app.state.destination_catalog_refreshed_at = refreshed_at
                    save_destination_catalog_cache(
                        resolved_settings,
                        merged_options,
                    )
                except Exception:
                    pass
                finally:
                    with app.state.destination_catalog_lock:
                        app.state.destination_catalog_refreshing = False

            Thread(target=worker, daemon=True).start()

        cached_options = app.state.destination_catalog
        if cached_options:
            refresh_destination_catalog_if_needed()
            return merge_destination_options(cached_options, fallback_options)

        refresh_destination_catalog_if_needed(force=True)
        return fallback_options

    def list_registered_providers() -> list[dict[str, str]]:
        with app.state.provider_catalog_lock:
            current_catalog = list(app.state.provider_catalog)
        return serialize_provider_catalog(current_catalog, settings=resolved_settings)

    def persist_registered_providers(provider_catalog: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized_catalog = normalize_provider_catalog_entries(provider_catalog)
        save_provider_catalog(resolved_settings, normalized_catalog)
        with app.state.provider_catalog_lock:
            app.state.provider_catalog = normalized_catalog
        if hasattr(app.state.scraper_service, "refresh_active_provider_slugs"):
            app.state.scraper_service.refresh_active_provider_slugs(
                tuple(
                    provider["provider_slug"]
                    for provider in normalized_catalog
                    if provider.get("provider_slug")
                )
            )
        return normalized_catalog

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        lang: str = Query(default="en"),
        destination_slug: str = Query(default=""),
        provider_slug: str = Query(default=""),
        min_price: str | None = Query(default=None),
        max_price: str | None = Query(default=None),
        min_validity_days: str | None = Query(default=None),
        min_data_gb: str | None = Query(default=None),
        sort_by: str = Query(default="price_amount"),
        sort_order: str = Query(default="asc"),
        message: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> HTMLResponse:
        resolved_lang = resolve_language(lang)
        messages = TRANSLATIONS[resolved_lang]
        filters = build_filters(
            destination_slug=destination_slug,
            provider_slug=provider_slug,
            min_price=min_price,
            max_price=max_price,
            min_validity_days=min_validity_days,
            min_data_gb=min_data_gb,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        plans = app.state.repository.query_plans(filters)
        average_price_per_gb = calculate_average_price_per_gb(plans)
        destinations = app.state.repository.list_destinations()
        providers = app.state.repository.list_providers()
        latest_run = app.state.repository.latest_scrape_run()
        available_scrape_destinations = resolve_available_destinations()
        available_scrape_destination_groups = build_destination_picker_groups(
            available_scrape_destinations
        )
        selected_scrape_destinations: list[str] = list(resolved_settings.supported_destinations)
        active_provider_slugs = resolve_active_provider_slugs(resolved_settings)
        response = templates.TemplateResponse(
            request,
            "index.html",
            {
                "plans": plans,
                "destinations": destinations,
                "providers": providers,
                "filters": filters,
                "message": message,
                "error": error,
                "latest_run": latest_run,
                "supported_destinations": ", ".join(resolved_settings.supported_destinations),
                "preset_provider_slugs": active_provider_slugs,
                "destination_match_mode": resolved_settings.destination_match_mode,
                "available_scrape_destinations": available_scrape_destinations,
                "available_scrape_destination_groups": available_scrape_destination_groups,
                "available_scrape_destinations_count": len(available_scrape_destinations),
                "destination_picker_placeholder": messages["destination_picker_placeholder"].format(
                    count=len(available_scrape_destinations)
                ),
                "selected_scrape_destinations": selected_scrape_destinations,
                "lang": resolved_lang,
                "alt_lang": "zh" if resolved_lang == "en" else "en",
                "t": messages,
                "destination_icon_url_for": lambda slug, name: resolve_destination_icon_url(
                    resolved_settings, slug, name
                ),
                "provider_icon_url_for": lambda slug: resolve_provider_icon_url(
                    resolved_settings, slug
                ),
                "average_price_per_gb": average_price_per_gb,
                "price_per_gb_delta_for": lambda value: describe_price_per_gb_delta(
                    value,
                    average_price_per_gb,
                ),
                "sort_link_for": lambda column: build_sort_link(
                    request,
                    filters,
                    column,
                    resolved_lang,
                ),
                "sort_indicator_for": lambda column: describe_sort_indicator(filters, column),
            },
        )
        response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/docs", response_class=HTMLResponse)
    def docs_page(
        request: Request,
        lang: str = Query(default="en"),
    ) -> HTMLResponse:
        resolved_lang = resolve_language(lang)
        messages = TRANSLATIONS[resolved_lang]
        registered_providers = list_registered_providers()
        response = templates.TemplateResponse(
            request,
            "docs.html",
            {
                "lang": resolved_lang,
                "alt_lang": "zh" if resolved_lang == "en" else "en",
                "t": messages,
                "provider_catalog": registered_providers,
                "provider_catalog_json": registered_providers,
                "provider_catalog_count_text": messages["docs_provider_count"].format(
                    count=len(registered_providers)
                ),
            },
        )
        response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/api/providers")
    def api_list_providers() -> JSONResponse:
        return JSONResponse({"providers": list_registered_providers()})

    @app.post("/api/providers")
    def api_add_provider(
        website_url: str = Form(default=""),
        lang: str = Form(default="en"),
    ) -> JSONResponse:
        resolved_lang = resolve_language(lang)
        messages = TRANSLATIONS[resolved_lang]
        try:
            provider_entry = register_provider_from_url(resolved_settings, website_url)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except httpx.HTTPError as exc:
            return JSONResponse(
                {"error": messages["scrape_failed"].format(error=exc)},
                status_code=502,
            )

        with app.state.provider_catalog_lock:
            current_catalog = list(app.state.provider_catalog)
        created = not any(
            provider["provider_slug"] == provider_entry["provider_slug"]
            for provider in current_catalog
        )
        updated_catalog = persist_registered_providers([*current_catalog, provider_entry])
        serialized_catalog = serialize_provider_catalog(updated_catalog, settings=resolved_settings)
        matching_provider = next(
            provider
            for provider in serialized_catalog
            if provider["provider_slug"] == provider_entry["provider_slug"]
        )
        return JSONResponse(
            {
                "created": created,
                "provider": matching_provider,
                "providers": serialized_catalog,
                "message": (
                    messages["docs_add_success"].format(name=matching_provider["provider_name"])
                    if created
                    else messages["docs_update_success"].format(name=matching_provider["provider_name"])
                ),
            },
            status_code=201 if created else 200,
        )

    @app.delete("/api/providers/{provider_slug}")
    def api_delete_provider(
        provider_slug: str,
        lang: str = Query(default="en"),
    ) -> JSONResponse:
        resolved_lang = resolve_language(lang)
        messages = TRANSLATIONS[resolved_lang]
        normalized_slug = provider_slug.strip().lower()
        with app.state.provider_catalog_lock:
            current_catalog = list(app.state.provider_catalog)
        deleted_provider = next(
            (provider for provider in current_catalog if provider["provider_slug"] == normalized_slug),
            None,
        )
        if deleted_provider is None:
            return JSONResponse({"error": messages["docs_delete_missing"]}, status_code=404)

        updated_catalog = persist_registered_providers(
            [
                provider
                for provider in current_catalog
                if provider["provider_slug"] != normalized_slug
            ]
        )
        return JSONResponse(
            {
                "deleted": True,
                "provider_slug": normalized_slug,
                "providers": serialize_provider_catalog(updated_catalog, settings=resolved_settings),
                "message": messages["docs_delete_success"].format(
                    name=deleted_provider["provider_name"]
                ),
            }
        )

    @app.post("/scrape")
    def run_scrape(
        destinations: str = Form(default=""),
        lang: str = Form(default="en"),
        match_mode: str = Form(default="strict"),
    ) -> RedirectResponse:
        resolved_lang = resolve_language(lang)
        messages = TRANSLATIONS[resolved_lang]
        resolved_match_mode = (
            match_mode if match_mode in {"strict", "relaxed"} else resolved_settings.destination_match_mode
        )
        destination_slugs = [
            item.strip().lower()
            for item in (destinations or ",".join(resolved_settings.supported_destinations)).split(",")
            if item.strip()
        ]
        run_id = app.state.repository.create_scrape_run(destination_slugs)
        try:
            app.state.repository.clear_plans()
            stats = app.state.scraper_service.scrape_destinations(
                destination_slugs,
                match_mode=resolved_match_mode,
            )
        except Exception as exc:
            app.state.repository.finish_scrape_run(
                run_id,
                status="failed",
                inserted_count=0,
                updated_count=0,
                skipped_count=0,
                error_summary=str(exc),
            )
            return RedirectResponse(
                url=f"/?lang={resolved_lang}&error={messages['scrape_failed'].format(error=exc)}",
                status_code=303,
            )

        app.state.repository.finish_scrape_run(
            run_id,
            status="completed",
            inserted_count=stats.inserted_count,
            updated_count=stats.updated_count,
            skipped_count=stats.skipped_count,
            error_summary=None,
        )
        return RedirectResponse(
            url=(
                f"/?lang={resolved_lang}&message="
                f"{messages['scrape_complete'].format(inserted=stats.inserted_count, updated=stats.updated_count, skipped=stats.skipped_count)}"
            ),
            status_code=303,
        )

    @app.post("/api/scrape-start")
    def api_scrape_start(
        destinations: str = Form(default=""),
        lang: str = Form(default="en"),
        match_mode: str = Form(default="strict"),
    ) -> JSONResponse:
        resolved_lang = resolve_language(lang)
        resolved_match_mode = (
            match_mode if match_mode in {"strict", "relaxed"} else resolved_settings.destination_match_mode
        )
        destination_slugs = [
            item.strip().lower()
            for item in (destinations or ",".join(resolved_settings.supported_destinations)).split(",")
            if item.strip()
        ]
        started, reason = start_background_scrape(destination_slugs, resolved_match_mode)
        if not started:
            return JSONResponse(
                {
                    "started": False,
                    "reason": reason,
                    "running": True,
                },
                status_code=409,
            )
        return JSONResponse(
            {
                "started": True,
                "running": True,
                "lang": resolved_lang,
                "destinations": destination_slugs,
                "match_mode": resolved_match_mode,
            }
        )

    @app.get("/api/scrape-status")
    def api_scrape_status() -> JSONResponse:
        latest_run = app.state.repository.latest_scrape_run()
        return JSONResponse(
            {
                "running": app.state.scrape_state["running"],
                "error": app.state.scrape_state["error"],
                "latest_run": None
                if latest_run is None
                else {
                    "id": latest_run.id,
                    "status": latest_run.status,
                    "started_at": latest_run.started_at,
                    "finished_at": latest_run.finished_at,
                    "destination_slugs": latest_run.destination_slugs,
                    "inserted_count": latest_run.inserted_count,
                    "updated_count": latest_run.updated_count,
                    "skipped_count": latest_run.skipped_count,
                    "error_summary": latest_run.error_summary,
                },
            }
        )

    @app.get("/export.csv")
    def export_csv(
        lang: str = Query(default="en"),
        destination_slug: str = Query(default=""),
        provider_slug: str = Query(default=""),
        min_price: str | None = Query(default=None),
        max_price: str | None = Query(default=None),
        min_validity_days: str | None = Query(default=None),
        min_data_gb: str | None = Query(default=None),
    ) -> Response:
        filters = build_filters(
            destination_slug=destination_slug,
            provider_slug=provider_slug,
            min_price=min_price,
            max_price=max_price,
            min_validity_days=min_validity_days,
            min_data_gb=min_data_gb,
        )
        rows = app.state.repository.query_plans(filters)
        csv_text = app.state.repository.export_csv(filters)
        filename = build_export_filename([str(row["destination_name"]) for row in rows])
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(content=csv_text, media_type="text/csv", headers=headers)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
