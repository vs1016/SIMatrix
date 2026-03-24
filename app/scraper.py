from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.config import Settings
from app.models import PlanRecord
from app.provider_catalog import resolve_active_provider_slugs
from app.repository import Repository, build_plan_source_key

DATA_RE = re.compile(r"^\d+(?:\.\d+)?(?:MB|GB)(?:\s*/day)?(?:\s*\+\s*.+)?$", re.IGNORECASE)
VALIDITY_RE = re.compile(r"^(?P<days>\d+)\s*Day(?:s)?$", re.IGNORECASE)
PRICE_RE = re.compile(r"^\$(?P<price>\d+(?:\.\d+)?)$")
PRICE_PER_GB_RE = re.compile(r"^\$(?P<price>\d+(?:\.\d+)?)/GB$", re.IGNORECASE)
NON_PURE_REGION_TERMS = (
    "global",
    "world",
    "worldwide",
    "north america",
    "south america",
    "latin america",
    "europe",
    "asia",
    "africa",
    "middle east",
    "caribbean",
    "americas",
    "multiple country",
    "multi country",
    "multi-country",
    "regional",
    "regions",
    "countries",
)
DESTINATION_CATALOG_EXCLUDED_SLUGS = {
    "",
    "en",
    "ja",
    "fr",
    "es",
    "it",
    "blog",
    "help",
    "about",
    "contact",
    "terms",
    "privacy",
    "providers",
    "search",
    "best-esim",
    "esim",
    "faq",
    "guides",
}
DESTINATION_ALIASES = {
    "usa": ("usa", "united states", "united states of america"),
    "uk": ("uk", "united kingdom", "great britain", "britain"),
}
DESTINATION_DISPLAY_NAME_OVERRIDES = {
    "usa": "USA",
    "uk": "UK",
    "uae": "UAE",
}


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    return path.split("/")[-1].lower()


def parse_data_amount_mb(data_text: str) -> float | None:
    match = re.match(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>MB|GB)", data_text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group("value"))
    unit = match.group("unit").upper()
    return value if unit == "MB" else value * 1024


def parse_validity_days(validity_text: str) -> int | None:
    match = VALIDITY_RE.match(validity_text.strip())
    if not match:
        return None
    return int(match.group("days"))


def clean_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [text.strip() for text in soup.stripped_strings if text.strip()]


def extract_destination_heading(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1")
    if title and "for" in title.get_text(" ", strip=True):
        heading = title.get_text(" ", strip=True)
        match = re.search(r"for\s+(?P<destination>.+)$", heading)
        if match:
            destination_name = match.group("destination").strip()
            return heading, destination_name
    return "", ""


def clean_destination_label(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^(?:[\U0001F1E6-\U0001F1FF]{2}\s*)+", "", cleaned)
    cleaned = re.sub(r"\s+\d[\d,]*\s+plans?$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(\d[\d,]*.*?\)$", "", cleaned)
    cleaned = re.sub(r"^[A-Z]{2,3}\s+(?=[A-Z][a-z])", "", cleaned)
    cleaned = re.sub(r"^[A-Z][a-z]\s+(?=[A-Z][a-z])", "", cleaned)
    return cleaned.strip(" -")


def looks_like_destination_slug(slug: str) -> bool:
    if slug in DESTINATION_CATALOG_EXCLUDED_SLUGS:
        return False
    if slug in {term.replace(" ", "-") for term in NON_PURE_REGION_TERMS}:
        return False
    return True


def humanize_destination_slug(slug: str) -> str:
    override = DESTINATION_DISPLAY_NAME_OVERRIDES.get(slug.lower())
    if override:
        return override
    return slug.replace("-", " ").title()


def parse_price_text(text: str) -> float | None:
    text = text.strip()
    match = re.match(r"^\$(?P<price>\d+(?:\.\d+)?)$", text)
    if not match:
        return None
    return float(match.group("price"))


def normalize_search_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def build_allowed_destination_aliases(destination_slug: str, destination_name: str) -> set[str]:
    aliases = {normalize_search_text(destination_name), normalize_search_text(destination_slug)}
    aliases.update(normalize_search_text(alias) for alias in DESTINATION_ALIASES.get(destination_slug.lower(), ()))
    return {alias for alias in aliases if alias}


def plan_matches_target_destination(
    plan_name: str,
    destination_slug: str,
    destination_name: str,
    known_region_names: set[str],
    match_mode: str = "strict",
) -> bool:
    normalized_plan_name = normalize_search_text(plan_name)
    allowed_aliases = build_allowed_destination_aliases(destination_slug, destination_name)

    if any(term in normalized_plan_name for term in NON_PURE_REGION_TERMS):
        return False

    forbidden_regions = known_region_names - allowed_aliases
    for region_name in forbidden_regions:
        if len(region_name) < 3:
            continue
        if region_name in normalized_plan_name:
            return False

    if match_mode == "relaxed":
        return True

    if not any(alias in normalized_plan_name for alias in allowed_aliases):
        return False

    return True


def build_known_region_names(flag_icon_dir: Path) -> set[str]:
    if not flag_icon_dir.exists():
        return set()
    region_names = {
        normalize_search_text(path.stem)
        for path in flag_icon_dir.iterdir()
        if path.is_file()
    }
    region_names.update(
        normalize_search_text(alias)
        for aliases in DESTINATION_ALIASES.values()
        for alias in aliases
    )
    return {name for name in region_names if name}


def _extract_card_text_values(card: Tag) -> list[str]:
    desktop_block = card.select_one("div.hidden.lg\\:flex.lg\\:flex-col.p-4")
    candidate = desktop_block or card
    texts: list[str] = []
    for value in candidate.stripped_strings:
        text = value.strip()
        if not text:
            continue
        texts.append(text)
    return texts


def parse_provider_cards(
    html: str,
    *,
    destination_slug: str,
    destination_name: str,
    provider_slug: str,
    source_url: str,
) -> list[PlanRecord]:
    soup = BeautifulSoup(html, "html.parser")
    provider_heading = soup.find("h1") or soup.find("h2")
    provider_name = provider_heading.get_text(" ", strip=True) if provider_heading else provider_slug
    provider_name = provider_name.replace(" eSIM Data Plans for " + destination_name, "").strip()
    provider_name = provider_name.replace("#", "").strip()

    plans: list[PlanRecord] = []
    for card in soup.select("div.space-y-2 > div.w-full"):
        values = _extract_card_text_values(card)
        if len(values) < 5:
            continue

        plan_name = values[0]
        data_text = next((value for value in values[1:] if DATA_RE.match(value)), "")
        validity_text = next((value for value in values[1:] if VALIDITY_RE.match(value)), "")
        price_amount = None
        price_per_gb = None
        coverage_type = next((value for value in values if value in {"5G", "4G"}), None)

        for index, value in enumerate(values):
            if PRICE_RE.match(value):
                if index + 1 < len(values) and values[index + 1] == "/GB":
                    if price_per_gb is None:
                        price_per_gb = parse_price_text(value)
                elif price_amount is None:
                    price_amount = parse_price_text(value)

        validity_days = parse_validity_days(validity_text)
        if not plan_name or not data_text or validity_days is None or price_amount is None:
            continue

        source_key = build_plan_source_key(
            destination_slug,
            provider_slug,
            plan_name,
            data_text,
            validity_days,
            price_amount,
        )
        plans.append(
            PlanRecord(
                source_key=source_key,
                destination_slug=destination_slug,
                destination_name=destination_name,
                provider_slug=provider_slug,
                provider_name=provider_name or provider_slug.replace("-", " ").title(),
                plan_name=plan_name,
                data_amount_text=data_text,
                data_amount_mb=parse_data_amount_mb(data_text),
                validity_days=validity_days,
                price_amount=price_amount,
                currency="USD",
                price_per_gb=price_per_gb,
                coverage_type=coverage_type,
                source_url=source_url,
                last_seen_at=datetime.now(UTC),
            )
        )

    unique_plans: dict[str, PlanRecord] = {}
    for plan in plans:
        unique_plans[plan.source_key] = plan
    return list(unique_plans.values())


def parse_provider_page(
    html: str,
    *,
    destination_slug: str,
    destination_name: str,
    provider_slug: str,
    source_url: str,
) -> list[PlanRecord]:
    card_plans = parse_provider_cards(
        html,
        destination_slug=destination_slug,
        destination_name=destination_name,
        provider_slug=provider_slug,
        source_url=source_url,
    )
    if card_plans:
        return card_plans

    lines = clean_lines(html)
    if not lines:
        return []

    soup = BeautifulSoup(html, "html.parser")
    provider_heading = soup.find("h1") or soup.find("h2")
    provider_name = provider_heading.get_text(" ", strip=True) if provider_heading else provider_slug
    provider_name = provider_name.replace(" eSIM Data Plans for " + destination_name, "").strip()
    provider_name = provider_name.replace("#", "").strip()

    plans: list[PlanRecord] = []
    in_catalog = False
    ignored_tokens = {
        "Apply Promo Codes",
        "To all applicable plans instantly",
        "Details",
        "View Details",
        "Official Website",
        "Promo Code",
        "Terms apply.",
        "5G",
        "4G",
        "Unlimited",
        "Verified",
        "Copy",
        "Single-country",
        "Multiple-country",
    }

    index = 0
    while index < len(lines):
        line = lines[index]
        if "Plan name" in line and "Price" in line:
            in_catalog = True
            index += 1
            continue
        if not in_catalog:
            index += 1
            continue
        if "FAQ" in line or line.startswith("Does ") or line.startswith("More eSIM Providers"):
            break
        if (
            line in ignored_tokens
            or DATA_RE.match(line)
            or VALIDITY_RE.match(line)
            or PRICE_RE.match(line)
            or PRICE_PER_GB_RE.match(line)
            or line.startswith("$")
            or "OFF" in line
        ):
            index += 1
            continue

        plan_name = line
        data_text = ""
        validity_days = None
        price_amount = None
        price_per_gb = None
        coverage_type = None
        lookahead = index + 1

        while lookahead < len(lines):
            current = lines[lookahead]
            if current == plan_name and data_text:
                break
            if current in ignored_tokens or "discount" in current.lower():
                lookahead += 1
                continue
            if DATA_RE.match(current) and not data_text:
                data_text = current
                lookahead += 1
                continue
            if VALIDITY_RE.match(current) and validity_days is None:
                validity_days = parse_validity_days(current)
                lookahead += 1
                continue
            if PRICE_PER_GB_RE.match(current) and price_per_gb is None:
                price_per_gb = float(PRICE_PER_GB_RE.match(current).group("price"))
                lookahead += 1
                continue
            if PRICE_RE.match(current) and price_amount is None:
                price_amount = float(PRICE_RE.match(current).group("price"))
                lookahead += 1
                continue
            if current in {"5G", "4G"} and coverage_type is None:
                coverage_type = current
                lookahead += 1
                continue
            if "FAQ" in current or current.startswith("Does "):
                break
            if data_text and validity_days is not None and price_amount is not None:
                break
            if (
                not DATA_RE.match(current)
                and not VALIDITY_RE.match(current)
                and not current.startswith("$")
                and current not in ignored_tokens
            ):
                break
            lookahead += 1

        if data_text and validity_days is not None and price_amount is not None:
            normalized_provider_name = provider_name or provider_slug.replace("-", " ").title()
            source_key = build_plan_source_key(
                destination_slug,
                provider_slug,
                plan_name,
                data_text,
                validity_days,
                price_amount,
            )
            plans.append(
                PlanRecord(
                    source_key=source_key,
                    destination_slug=destination_slug,
                    destination_name=destination_name,
                    provider_slug=provider_slug,
                    provider_name=normalized_provider_name,
                    plan_name=plan_name,
                    data_amount_text=data_text,
                    data_amount_mb=parse_data_amount_mb(data_text),
                    validity_days=validity_days,
                    price_amount=price_amount,
                    currency="USD",
                    price_per_gb=price_per_gb,
                    coverage_type=coverage_type,
                    source_url=source_url,
                    last_seen_at=datetime.now(UTC),
                )
            )
            index = lookahead
            continue

        index += 1

    unique_plans: dict[str, PlanRecord] = {}
    for plan in plans:
        unique_plans[plan.source_key] = plan
    return list(unique_plans.values())


def extract_provider_links(html: str, destination_slug: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select(f'a[href^="/{destination_slug}/"]'):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        full_url = urljoin(base_url + "/", href.lstrip("/"))
        parsed = urlparse(full_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) != 2:
            continue
        if segments[0].lower() != destination_slug.lower():
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        links.append(full_url)
    return links


def extract_destination_catalog(html: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    catalog: dict[str, dict[str, str]] = {}
    for anchor in soup.select('a[href^="/"]'):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        full_url = urljoin(base_url + "/", href.lstrip("/"))
        parsed = urlparse(full_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) != 1:
            continue

        slug = segments[0].lower()
        if not looks_like_destination_slug(slug):
            continue

        text_candidates = [
            anchor.get_text(" ", strip=True),
            anchor.get("title", ""),
            anchor.get("aria-label", ""),
        ]
        first_image = anchor.find("img")
        if first_image is not None:
            text_candidates.append(first_image.get("alt", ""))
        destination_name = next(
            (clean_destination_label(candidate) for candidate in text_candidates if clean_destination_label(candidate)),
            "",
        )
        if not destination_name:
            continue
        if slug not in catalog:
            catalog[slug] = {
                "slug": slug,
                "name": destination_name,
            }
    return sorted(catalog.values(), key=lambda item: item["name"].lower())


def extract_destination_catalog_from_sitemap(
    sitemap_xml: str,
    base_url: str,
    *,
    existing_catalog: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    canonical_host = urlparse(base_url).netloc.lower()
    catalog: dict[str, dict[str, str]] = {
        str(item["slug"]).strip().lower(): {
            "slug": str(item["slug"]).strip().lower(),
            "name": str(item["name"]).strip(),
        }
        for item in (existing_catalog or [])
        if str(item.get("slug", "")).strip() and str(item.get("name", "")).strip()
    }
    seen_slugs = set(catalog)

    for loc in re.findall(r"<loc>(.*?)</loc>", sitemap_xml):
        parsed = urlparse(loc.strip())
        if parsed.netloc.lower() != canonical_host:
            continue
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) != 1:
            continue

        slug = segments[0].lower()
        if slug in seen_slugs or not looks_like_destination_slug(slug):
            continue

        seen_slugs.add(slug)
        catalog[slug] = {
            "slug": slug,
            "name": humanize_destination_slug(slug),
        }

    return sorted(catalog.values(), key=lambda item: item["name"].lower())


def extract_provider_logo_urls(html: str, destination_slug: str, base_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    logo_urls: dict[str, str] = {}
    for anchor in soup.select(f'a[href^="/{destination_slug}/"]'):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        full_url = urljoin(base_url + "/", href.lstrip("/"))
        provider_slug = slug_from_url(full_url)
        if not provider_slug:
            continue
        for image in anchor.find_all("img", src=True):
            src = image.get("src", "").strip()
            if "/assets/pictures/provider/" not in src:
                continue
            logo_urls[provider_slug] = urljoin(base_url + "/", src.lstrip("/"))
            break
    return logo_urls


def extract_provider_logo_url_from_provider_page(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for image in soup.find_all("img", src=True):
        src = image.get("src", "").strip()
        if "/assets/pictures/provider/" in src:
            return urljoin(base_url + "/", src.lstrip("/"))
    return None


def list_cached_provider_logo_slugs(provider_icon_dir: Path) -> set[str]:
    return {
        path.stem.strip().lower()
        for path in provider_icon_dir.glob("*")
        if path.is_file() and path.stem.strip()
    }


def download_provider_logo(
    client: httpx.Client,
    provider_slug: str,
    logo_url: str,
    provider_icon_dir: Path,
) -> bool:
    normalized_provider_slug = provider_slug.strip().lower()
    existing_logo_paths = [
        path
        for path in provider_icon_dir.glob(f"{normalized_provider_slug}.*")
        if path.is_file()
    ]
    if existing_logo_paths:
        return False

    suffix = Path(urlparse(logo_url).path).suffix.lower() or ".png"
    target_path = provider_icon_dir / f"{normalized_provider_slug}{suffix}"
    if target_path.exists():
        return False

    response = client.get(logo_url)
    response.raise_for_status()
    target_path.write_bytes(response.content)
    return True


@dataclass(slots=True)
class ScrapeStats:
    inserted_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    providers_visited: int = 0


@dataclass(slots=True)
class ProviderScrapeResult:
    index: int
    provider_slug: str
    plans: list[PlanRecord]
    logo_cached: bool


class EsimDbScraperService:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self.known_region_names = build_known_region_names(settings.flag_icon_dir)
        self.active_provider_slugs = resolve_active_provider_slugs(settings)

    def refresh_active_provider_slugs(
        self,
        active_provider_slugs: Iterable[str] | None = None,
    ) -> None:
        source_slugs = (
            resolve_active_provider_slugs(self.settings)
            if active_provider_slugs is None
            else active_provider_slugs
        )
        self.active_provider_slugs = tuple(
            str(provider_slug).strip().lower()
            for provider_slug in source_slugs
            if str(provider_slug).strip()
        )

    def _http_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.settings.user_agent},
        )

    def _fetch_text(self, client: httpx.Client, url: str) -> str:
        response = client.get(url)
        response.raise_for_status()
        return response.text

    def _filter_provider_links(self, provider_links: list[str]) -> list[str]:
        active_provider_slugs = self.active_provider_slugs
        allowed = set(active_provider_slugs)
        filtered = [
            provider_url
            for provider_url in provider_links
            if slug_from_url(provider_url) in allowed
        ]
        filtered.sort(key=lambda url: active_provider_slugs.index(slug_from_url(url)))
        return filtered

    def _dedupe_provider_links(self, provider_links: list[str]) -> list[str]:
        unique_links: list[str] = []
        seen_provider_slugs: set[str] = set()
        for provider_url in provider_links:
            provider_slug = slug_from_url(provider_url)
            if not provider_slug or provider_slug in seen_provider_slugs:
                continue
            seen_provider_slugs.add(provider_slug)
            unique_links.append(provider_url)
        return unique_links

    def _scrape_provider(
        self,
        *,
        index: int,
        destination_slug: str,
        destination_name: str,
        provider_url: str,
        logo_url: str | None,
        match_mode: str,
        cached_provider_logo_slugs: set[str],
    ) -> ProviderScrapeResult:
        provider_slug = slug_from_url(provider_url)
        logo_cached = provider_slug in cached_provider_logo_slugs
        with self._http_client() as client:
            if logo_url and not logo_cached:
                download_provider_logo(
                    client,
                    provider_slug,
                    logo_url,
                    self.settings.provider_icon_dir,
                )
                logo_cached = True

            provider_html = self._fetch_text(client, provider_url)

            if not logo_cached and not logo_url:
                fallback_logo_url = extract_provider_logo_url_from_provider_page(
                    provider_html,
                    self.settings.base_url,
                )
                if fallback_logo_url:
                    download_provider_logo(
                        client,
                        provider_slug,
                        fallback_logo_url,
                        self.settings.provider_icon_dir,
                    )
                    logo_cached = True

        plans = parse_provider_page(
            provider_html,
            destination_slug=destination_slug,
            destination_name=destination_name,
            provider_slug=provider_slug,
            source_url=provider_url,
        )
        plans = [
            plan
            for plan in plans
            if plan_matches_target_destination(
                plan.plan_name,
                destination_slug,
                destination_name,
                self.known_region_names,
                match_mode,
            )
        ]
        return ProviderScrapeResult(
            index=index,
            provider_slug=provider_slug,
            plans=plans,
            logo_cached=logo_cached,
        )

    def _scrape_provider_batch(
        self,
        *,
        destination_slug: str,
        destination_name: str,
        provider_links: list[str],
        provider_logo_urls: dict[str, str],
        match_mode: str,
        cached_provider_logo_slugs: set[str],
    ) -> list[ProviderScrapeResult]:
        if not provider_links:
            return []

        provider_tasks = [
            {
                "index": index,
                "destination_slug": destination_slug,
                "destination_name": destination_name,
                "provider_url": provider_url,
                "logo_url": provider_logo_urls.get(slug_from_url(provider_url)),
                "match_mode": match_mode,
                "cached_provider_logo_slugs": cached_provider_logo_slugs,
            }
            for index, provider_url in enumerate(provider_links)
        ]
        worker_count = min(self.settings.provider_fetch_workers, len(provider_tasks))
        if worker_count <= 1:
            return [self._scrape_provider(**task) for task in provider_tasks]

        results: list[ProviderScrapeResult] = []
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="rtg-provider") as executor:
            futures = [executor.submit(self._scrape_provider, **task) for task in provider_tasks]
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda result: result.index)
        return results

    def list_available_destinations(self) -> list[dict[str, str]]:
        with self._http_client() as client:
            homepage_catalog: list[dict[str, str]] = []
            try:
                homepage_html = self._fetch_text(client, self.settings.base_url)
            except httpx.HTTPError:
                homepage_html = ""
            if homepage_html:
                homepage_catalog = extract_destination_catalog(homepage_html, self.settings.base_url)
            try:
                sitemap_xml = self._fetch_text(client, f"{self.settings.base_url}/en/sitemap.xml")
            except httpx.HTTPError:
                if homepage_catalog:
                    return homepage_catalog
                return homepage_catalog
        return extract_destination_catalog_from_sitemap(
            sitemap_xml,
            self.settings.base_url,
            existing_catalog=homepage_catalog,
        )

    def scrape_destinations(
        self,
        destination_slugs: Iterable[str],
        *,
        match_mode: str | None = None,
    ) -> ScrapeStats:
        stats = ScrapeStats()
        resolved_match_mode = match_mode or self.settings.destination_match_mode
        cached_provider_logo_slugs = list_cached_provider_logo_slugs(
            self.settings.provider_icon_dir
        )
        with self._http_client() as client:
            for destination_slug in destination_slugs:
                destination_url = f"{self.settings.base_url}/{destination_slug}"
                destination_html = self._fetch_text(client, destination_url)
                _, destination_name = extract_destination_heading(destination_html)
                destination_name = destination_name or destination_slug.replace("-", " ").title()
                provider_links = extract_provider_links(
                    destination_html, destination_slug, self.settings.base_url
                )
                provider_logo_urls = extract_provider_logo_urls(
                    destination_html, destination_slug, self.settings.base_url
                )
                provider_links = self._filter_provider_links(provider_links)
                provider_links = self._dedupe_provider_links(provider_links)
                if self.settings.max_providers_per_destination is not None:
                    provider_links = provider_links[: self.settings.max_providers_per_destination]

                provider_results = self._scrape_provider_batch(
                    destination_slug=destination_slug,
                    destination_name=destination_name,
                    provider_links=provider_links,
                    provider_logo_urls=provider_logo_urls,
                    match_mode=resolved_match_mode,
                    cached_provider_logo_slugs=cached_provider_logo_slugs,
                )
                stats.providers_visited += len(provider_results)
                cached_provider_logo_slugs.update(
                    result.provider_slug for result in provider_results if result.logo_cached
                )

                with self.repository.transaction():
                    for provider_result in provider_results:
                        self.repository.prune_provider_destination_plans(
                            destination_slug,
                            provider_result.provider_slug,
                            {plan.source_key for plan in provider_result.plans},
                        )
                        for plan in provider_result.plans:
                            outcome = self.repository.upsert_plan(plan)
                            if outcome == "inserted":
                                stats.inserted_count += 1
                            elif outcome == "updated":
                                stats.updated_count += 1
                            else:
                                stats.skipped_count += 1
        return stats
