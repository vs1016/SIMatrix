from __future__ import annotations

import time
from pathlib import Path

from app.assets import resolve_destination_icon_url
from app.config import Settings, get_settings
from app.main import calculate_average_price_per_gb, describe_price_per_gb_delta
from app.provider_catalog import save_provider_catalog
from app.presentation import sanitize_plan_display_name
from app.repository import Repository
from app.scraper import (
    EsimDbScraperService,
    ProviderScrapeResult,
    build_known_region_names,
    clean_destination_label,
    download_provider_logo,
    extract_destination_catalog,
    extract_destination_catalog_from_sitemap,
    extract_provider_links,
    extract_provider_logo_urls,
    extract_provider_logo_url_from_provider_page,
    plan_matches_target_destination,
    parse_provider_page,
)


def test_parse_provider_page_extracts_normalized_plans() -> None:
    html = Path("tests/fixtures/esimdb_provider_page.html").read_text(encoding="utf-8")

    plans = parse_provider_page(
        html,
        destination_slug="usa",
        destination_name="United States of America",
        provider_slug="esimnexa",
        source_url="https://esimdb.com/usa/esimnexa",
    )

    assert len(plans) == 2
    assert plans[0].provider_name == "eSIMNEXA"
    assert plans[0].plan_name == "USA 1GB 3Days"
    assert plans[0].data_amount_mb == 1024
    assert plans[0].validity_days == 3
    assert plans[0].price_amount == 1.0
    assert plans[0].price_per_gb == 1.0


def test_extract_provider_links_returns_unique_provider_urls() -> None:
    html = """
    <html><body>
      <a href="/usa/esimnexa">One</a>
      <a href="/usa/esimnexa">Duplicate</a>
      <a href="/usa/saily">Two</a>
      <a href="/usa">Ignore</a>
      <a href="/other/place">Ignore</a>
    </body></html>
    """
    links = extract_provider_links(html, "usa", "https://esimdb.com")
    assert links == [
        "https://esimdb.com/usa/esimnexa",
        "https://esimdb.com/usa/saily",
    ]


def test_parse_provider_page_handles_current_live_like_card_markup() -> None:
    html = Path("tests/fixtures/esimdb_provider_page_live_like.html").read_text(encoding="utf-8")

    plans = parse_provider_page(
        html,
        destination_slug="usa",
        destination_name="USA",
        provider_slug="esimnexa",
        source_url="https://esimdb.com/usa/esimnexa",
    )

    assert len(plans) == 2
    assert plans[0].plan_name == "USA 1GB 3Days"
    assert plans[0].price_amount == 1.0
    assert plans[0].price_per_gb == 1.0
    assert plans[0].coverage_type == "5G"
    assert plans[1].plan_name == "USA 3GB 7Days"
    assert plans[1].price_amount == 7.0


def test_scraper_filters_to_preset_provider_whitelist(app_components) -> None:
    settings, repository = app_components
    settings = Settings(
        base_url=settings.base_url,
        project_root=settings.project_root,
        data_dir=settings.data_dir,
        database_path=settings.database_path,
        flag_icon_dir=settings.flag_icon_dir,
        provider_icon_dir=settings.provider_icon_dir,
        supported_destinations=settings.supported_destinations,
        preset_provider_slugs=("airalo", "bytesim"),
        destination_match_mode=settings.destination_match_mode,
        max_providers_per_destination=settings.max_providers_per_destination,
        provider_fetch_workers=settings.provider_fetch_workers,
        http_timeout_seconds=settings.http_timeout_seconds,
        user_agent=settings.user_agent,
    )
    service = EsimDbScraperService(settings, repository)

    provider_links = [
        "https://esimdb.com/usa/airalo",
        "https://esimdb.com/usa/billionconnect",
        "https://esimdb.com/usa/bytesim",
    ]

    assert service._filter_provider_links(provider_links) == [
        "https://esimdb.com/usa/airalo",
        "https://esimdb.com/usa/bytesim",
    ]


def test_scraper_filters_provider_links_using_local_provider_catalog(app_components) -> None:
    settings, repository = app_components
    save_provider_catalog(
        settings,
        [
            {
                "provider_slug": "bytesim",
                "provider_name": "ByteSIM",
                "website_url": "https://esimdb.com/usa/bytesim",
                "official_website_url": "",
                "added_at": "2026-03-24T10:00:00+00:00",
            }
        ],
    )
    service = EsimDbScraperService(settings, repository)

    provider_links = [
        "https://esimdb.com/usa/airalo",
        "https://esimdb.com/usa/bytesim",
    ]

    assert service._filter_provider_links(provider_links) == [
        "https://esimdb.com/usa/bytesim",
    ]


def test_scraper_refresh_active_provider_slugs_updates_in_memory_whitelist(app_components) -> None:
    settings, repository = app_components
    service = EsimDbScraperService(settings, repository)

    service.refresh_active_provider_slugs(("nomad",))

    assert service._filter_provider_links(
        [
            "https://esimdb.com/usa/airalo",
            "https://esimdb.com/usa/nomad",
        ]
    ) == ["https://esimdb.com/usa/nomad"]


def test_extract_provider_logo_urls_returns_provider_assets() -> None:
    html = """
    <html><body>
      <a href="/usa/airalo"><img src="/assets/pictures/provider/airalo_tiny.jpg" alt="Airalo"></a>
      <a href="/usa/bytesim"><img src="/assets/pictures/provider/bytesim_tiny.jpg" alt="ByteSIM"></a>
      <a href="/usa/bytesim"><img src="/_nuxt/verified.svg" alt="certified"></a>
    </body></html>
    """
    logos = extract_provider_logo_urls(html, "usa", "https://esimdb.com")
    assert logos == {
        "airalo": "https://esimdb.com/assets/pictures/provider/airalo_tiny.jpg",
        "bytesim": "https://esimdb.com/assets/pictures/provider/bytesim_tiny.jpg",
    }


def test_clean_destination_label_removes_country_code_prefixes() -> None:
    assert clean_destination_label("BB Barbados") == "Barbados"
    assert clean_destination_label("BM Bermuda") == "Bermuda"
    assert clean_destination_label("BR Brazil") == "Brazil"
    assert clean_destination_label("BS Bahamas") == "Bahamas"
    assert clean_destination_label("BW Botswana") == "Botswana"
    assert clean_destination_label("🇦🇷 Argentina") == "Argentina"


def test_resolve_destination_icon_url_uses_local_flag_assets(app_components) -> None:
    settings, _ = app_components
    icon_url = resolve_destination_icon_url(settings, "usa", "United States of America")
    assert icon_url == "/flags/united states.png"


def test_default_provider_presets_match_live_slugs() -> None:
    settings = get_settings()
    assert settings.preset_provider_slugs == (
        "airalo",
        "nomad",
        "textr",
        "billionconnect",
        "bytesim",
    )


def test_plan_matches_target_destination_rejects_global_and_other_regions(app_components) -> None:
    settings, _ = app_components
    known_region_names = build_known_region_names(settings.flag_icon_dir)

    assert plan_matches_target_destination(
        "USA 1GB 7Days",
        "usa",
        "United States of America",
        known_region_names,
    )
    assert plan_matches_target_destination(
        "United States 5GB 30Days",
        "usa",
        "United States of America",
        known_region_names,
    )
    assert not plan_matches_target_destination(
        "Global eSIM [45 countries] 7 Days 5GB",
        "usa",
        "United States of America",
        known_region_names,
    )
    assert not plan_matches_target_destination(
        "USA Canada 5GB 7Days",
        "usa",
        "United States of America",
        known_region_names,
    )
    assert not plan_matches_target_destination(
        "North America eSIM [6 countries] 7 Days 5GB",
        "usa",
        "United States of America",
        known_region_names,
    )


def test_relaxed_mode_allows_target_page_plans_without_explicit_country_name(app_components) -> None:
    settings, _ = app_components
    known_region_names = build_known_region_names(settings.flag_icon_dir)

    assert not plan_matches_target_destination(
        "Discover - 10 GB",
        "usa",
        "United States of America",
        known_region_names,
        "strict",
    )
    assert plan_matches_target_destination(
        "Discover - 10 GB",
        "usa",
        "United States of America",
        known_region_names,
        "relaxed",
    )
    assert not plan_matches_target_destination(
        "Global eSIM [45 countries] 7 Days 5GB",
        "usa",
        "United States of America",
        known_region_names,
        "relaxed",
    )


def test_sanitize_plan_display_name_removes_data_and_validity_noise() -> None:
    assert sanitize_plan_display_name("USA eSIM 1 Day 500MB/Day") == "USA eSIM"
    assert sanitize_plan_display_name("United States 7 Days 5GB") == "United States"
    assert sanitize_plan_display_name("USA Unlimited 30 Days") == "USA"


def test_price_per_gb_delta_uses_current_average() -> None:
    plans = [
        {"price_per_gb": 1.0},
        {"price_per_gb": 2.0},
        {"price_per_gb": 3.0},
    ]
    average = calculate_average_price_per_gb(plans)
    assert average == 2.0
    assert describe_price_per_gb_delta(3.0, average) == {
        "label": "+50%",
        "tone": "over",
        "value": 0.5,
    }
    assert describe_price_per_gb_delta(1.0, average) == {
        "label": "-50%",
        "tone": "under",
        "value": -0.5,
    }


def test_extract_provider_logo_url_from_provider_page_finds_logo_asset() -> None:
    html = """
    <html><body>
      <img src="/_nuxt/logo.svg" alt="eSIMDB logo">
      <img src="/assets/pictures/provider/nomadesim_tiny.jpg" alt="Nomad">
    </body></html>
    """
    assert extract_provider_logo_url_from_provider_page(html, "https://esimdb.com") == (
        "https://esimdb.com/assets/pictures/provider/nomadesim_tiny.jpg"
    )


def test_download_provider_logo_skips_when_any_cached_logo_exists(app_components) -> None:
    settings, _ = app_components
    cached_logo_path = settings.provider_icon_dir / "airalo.webp"
    cached_logo_path.write_bytes(b"cached-logo")

    class FailingClient:
        def get(self, url: str):  # pragma: no cover - should never be called
            raise AssertionError(f"unexpected logo download for {url}")

    downloaded = download_provider_logo(
        FailingClient(),
        "airalo",
        "https://esimdb.com/assets/pictures/provider/airalo_tiny.jpg",
        settings.provider_icon_dir,
    )

    assert not downloaded
    assert cached_logo_path.read_bytes() == b"cached-logo"
    assert not (settings.provider_icon_dir / "airalo.jpg").exists()


def test_scraper_dedupes_provider_links_by_slug(app_components) -> None:
    settings, repository = app_components
    service = EsimDbScraperService(settings, repository)

    provider_links = [
        "https://esimdb.com/usa/airalo",
        "https://esimdb.com/usa/airalo/",
        "https://esimdb.com/usa/airalo?ref=homepage",
        "https://esimdb.com/usa/bytesim",
    ]

    assert service._dedupe_provider_links(provider_links) == [
        "https://esimdb.com/usa/airalo",
        "https://esimdb.com/usa/bytesim",
    ]


def test_scrape_provider_batch_fetches_providers_in_parallel(app_components, monkeypatch) -> None:
    settings, repository = app_components
    settings = Settings(
        base_url=settings.base_url,
        project_root=settings.project_root,
        data_dir=settings.data_dir,
        database_path=settings.database_path,
        flag_icon_dir=settings.flag_icon_dir,
        provider_icon_dir=settings.provider_icon_dir,
        supported_destinations=settings.supported_destinations,
        preset_provider_slugs=settings.preset_provider_slugs,
        destination_match_mode=settings.destination_match_mode,
        max_providers_per_destination=None,
        provider_fetch_workers=4,
        http_timeout_seconds=settings.http_timeout_seconds,
        user_agent=settings.user_agent,
    )
    service = EsimDbScraperService(settings, repository)

    def fake_scrape_provider(**task_kwargs):
        time.sleep(0.2)
        return ProviderScrapeResult(
            index=task_kwargs["index"],
            provider_slug=task_kwargs["provider_url"].rstrip("/").split("/")[-1].split("?")[0],
            plans=[],
            logo_cached=False,
        )

    monkeypatch.setattr(service, "_scrape_provider", fake_scrape_provider)

    started_at = time.perf_counter()
    results = service._scrape_provider_batch(
        destination_slug="usa",
        destination_name="United States of America",
        provider_links=[
            "https://esimdb.com/usa/airalo",
            "https://esimdb.com/usa/nomad",
            "https://esimdb.com/usa/textr",
            "https://esimdb.com/usa/bytesim",
        ],
        provider_logo_urls={},
        match_mode="strict",
        cached_provider_logo_slugs=set(),
    )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.6
    assert [result.provider_slug for result in results] == [
        "airalo",
        "nomad",
        "textr",
        "bytesim",
    ]


def test_extract_destination_catalog_excludes_locale_switch_links() -> None:
    html = """
    <html><body>
      <a href="/fr">Français</a>
      <a href="/es">Español</a>
      <a href="/usa">USA United States of America</a>
      <a href="/japan">Japan</a>
    </body></html>
    """

    items = extract_destination_catalog(html, "https://esimdb.com")

    assert items == [
        {"slug": "japan", "name": "Japan"},
        {"slug": "usa", "name": "United States of America"},
    ]


def test_extract_destination_catalog_from_sitemap_merges_missing_destinations() -> None:
    sitemap_xml = """
    <urlset>
      <url><loc>https://esimdb.com/</loc></url>
      <url><loc>https://esimdb.com/en</loc></url>
      <url><loc>https://esimdb.com/usa</loc></url>
      <url><loc>https://esimdb.com/uae</loc></url>
      <url><loc>https://esimdb.com/south-korea</loc></url>
      <url><loc>https://esimdb.com/usa/airalo</loc></url>
    </urlset>
    """

    items = extract_destination_catalog_from_sitemap(
        sitemap_xml,
        "https://esimdb.com",
        existing_catalog=[{"slug": "usa", "name": "United States of America"}],
    )

    assert items == [
        {"slug": "south-korea", "name": "South Korea"},
        {"slug": "uae", "name": "UAE"},
        {"slug": "usa", "name": "United States of America"},
    ]
