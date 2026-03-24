from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient

from app.main import (
    build_export_filename,
    create_app,
    normalize_destination_display_name,
    resolve_destination_display_code,
)
from app.models import PlanFilters, PlanRecord
from app.provider_catalog import provider_catalog_path
from app.repository import Repository, build_plan_source_key


@dataclass
class FakeStats:
    inserted_count: int
    updated_count: int
    skipped_count: int


class FakeScraperService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def scrape_destinations(self, destination_slugs, **kwargs):
        destination_slug = list(destination_slugs)[0]
        plan = PlanRecord(
            source_key=build_plan_source_key(
                destination_slug, "esimnexa", "USA 1GB 3Days", "1GB", 3, 1.0
            ),
            destination_slug=destination_slug,
            destination_name="United States of America",
            provider_slug="esimnexa",
            provider_name="eSIMNEXA",
            plan_name="USA 1GB 3Days",
            data_amount_text="1GB",
            data_amount_mb=1024,
            validity_days=3,
            price_amount=1.0,
            currency="USD",
            price_per_gb=1.0,
            coverage_type="5G",
            source_url="https://esimdb.com/usa/esimnexa",
            last_seen_at=datetime.now(UTC),
        )
        self.repository.upsert_plan(plan)
        return FakeStats(inserted_count=1, updated_count=0, skipped_count=0)

    def list_available_destinations(self):
        return [
            {"slug": "usa", "name": "United States of America"},
            {"slug": "japan", "name": "Japan"},
        ]


def test_dashboard_empty_state(client) -> None:
    test_client, _ = client
    response = test_client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, max-age=0, must-revalidate"
    assert "No plans match the current view." in response.text
    assert "FILTERABLE EXPORT" not in response.text
    assert 'id="loading-overlay"' in response.text
    assert "Latest Run" not in response.text
    assert "SIMatrix" in response.text
    assert "More" in response.text
    assert 'class="hero-stage"' in response.text
    assert 'class="hero-map-stage"' in response.text
    assert 'data-destination-bubbles' in response.text
    assert "Get Started" in response.text
    assert "Plan Browser" not in response.text


def test_dashboard_uses_destination_picker_for_scrape_targets(app_components) -> None:
    settings, repository = app_components
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )
    with TestClient(app) as test_client:
        response = test_client.get("/")
        assert response.status_code == 200
        assert 'data-destination-picker' in response.text
        assert 'data-destination-option' in response.text
        assert 'name="destinations"' in response.text
        assert 'placeholder="usa"' not in response.text
        assert 'value="usa"' in response.text
        assert 'class="destination-option-code"' not in response.text
        assert "{{ t.source }}" not in response.text
        assert 'data-row-href="' not in response.text


def test_dashboard_supports_chinese_language_toggle(client) -> None:
    test_client, _ = client
    response = test_client.get("/?lang=zh")
    assert response.status_code == 200
    assert "SIMatrix" in response.text
    assert "loading-overlay" in response.text
    assert "\u5f00\u59cb\u6293\u53d6" in response.text
    assert "\u4e0b\u8f7d CSV" in response.text
    assert "\u67e5\u627e\u4f60\u7684\u76ee\u7684\u5730" in response.text
    assert "\u66f4\u591a" in response.text


def test_docs_page_renders_provider_registry(app_components) -> None:
    settings, repository = app_components
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )
    with TestClient(app) as test_client:
        response = test_client.get("/docs?lang=en")
        assert response.status_code == 200
        assert "Manage active providers" in response.text
        assert "Add Provider" in response.text
        assert "5 providers currently active" in response.text
        assert "Airalo" in response.text


def test_provider_registry_api_adds_and_deletes_provider(app_components, monkeypatch) -> None:
    settings, repository = app_components
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )

    monkeypatch.setattr(
        "app.main.register_provider_from_url",
        lambda resolved_settings, website_url: {
            "provider_slug": "esimnexa",
            "provider_name": "eSIMNEXA",
            "website_url": website_url,
            "official_website_url": "https://esimnexa.com",
            "added_at": "2026-03-24T10:30:00+00:00",
        },
    )

    with TestClient(app) as test_client:
        add_response = test_client.post(
            "/api/providers",
            data={"website_url": "https://esimdb.com/usa/esimnexa", "lang": "en"},
        )
        assert add_response.status_code == 201
        add_payload = add_response.json()
        assert add_payload["created"] is True
        assert add_payload["provider"]["provider_slug"] == "esimnexa"
        assert any(
            provider["provider_slug"] == "esimnexa" for provider in add_payload["providers"]
        )

        saved_catalog = json.loads(provider_catalog_path(settings).read_text(encoding="utf-8"))
        assert any(provider["provider_slug"] == "esimnexa" for provider in saved_catalog)

        docs_response = test_client.get("/docs")
        assert docs_response.status_code == 200
        assert "eSIMNEXA" in docs_response.text

        delete_response = test_client.delete("/api/providers/esimnexa?lang=en")
        assert delete_response.status_code == 200
        delete_payload = delete_response.json()
        assert delete_payload["deleted"] is True
        assert all(
            provider["provider_slug"] != "esimnexa" for provider in delete_payload["providers"]
        )

        refreshed_catalog = json.loads(provider_catalog_path(settings).read_text(encoding="utf-8"))
        assert all(provider["provider_slug"] != "esimnexa" for provider in refreshed_catalog)


def test_provider_registry_api_returns_json_error_when_provider_fetch_fails(app_components, monkeypatch) -> None:
    settings, repository = app_components
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )

    monkeypatch.setattr(
        "app.main.register_provider_from_url",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.HTTPError("provider fetch failed")),
    )

    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/providers",
            data={"website_url": "https://bytesim.com", "lang": "en"},
        )
        assert response.status_code == 502
        assert response.json()["error"] == "Scrape failed: provider fetch failed"


def test_normalize_destination_display_name_removes_slug_prefix() -> None:
    assert normalize_destination_display_name("ar", "AR Argentina") == "Argentina"
    assert normalize_destination_display_name("ar", "Ar Argentina") == "Argentina"
    assert normalize_destination_display_name("argentina", "Ar Argentina") == "Argentina"
    assert normalize_destination_display_name("usa", "USA United States of America") == "United States of America"
    assert normalize_destination_display_name("austria", "AT Austria") == "Austria"
    assert normalize_destination_display_name("australia", "AU Australia") == "Australia"
    assert normalize_destination_display_name("aruba", "Aw Aruba") == "Aruba"
    assert normalize_destination_display_name("barbados", "Bb Barbados") == "Barbados"


def test_resolve_destination_display_code_prefers_upstream_country_code() -> None:
    assert resolve_destination_display_code("austria", "AT Austria") == "AT"
    assert resolve_destination_display_code("aruba", "Aw Aruba") == "AW"
    assert resolve_destination_display_code("barbados", "Bb Barbados") == "BB"


def test_manual_scrape_populates_dashboard_and_csv(app_components) -> None:
    settings, repository = app_components
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )
    with TestClient(app) as test_client:
        scrape_response = test_client.post(
            "/scrape",
            data={"destinations": "usa"},
            follow_redirects=True,
        )
        assert scrape_response.status_code == 200
        assert "USA 1GB 3Days" in scrape_response.text
        assert 'class="table-sort-link"' in scrape_response.text
        assert 'data-row-href="https://esimdb.com/usa/esimnexa"' in scrape_response.text
        assert ">Source<" not in scrape_response.text

        csv_response = test_client.get("/export.csv?destination_slug=usa")
        assert csv_response.status_code == 200
        assert csv_response.headers["content-disposition"] == (
            f'attachment; filename="{build_export_filename(["United States of America"])}"'
        )
        assert "provider_name" in csv_response.text
        assert "display_plan_name" in csv_response.text
        assert "raw_plan_name" in csv_response.text
        assert ",USA,USA 1GB 3Days," in csv_response.text
        assert "USA 1GB 3Days" in csv_response.text
        assert "eSIMNEXA" in csv_response.text


def test_scrape_clears_existing_plans_before_inserting_new_results(app_components) -> None:
    settings, repository = app_components
    stale = PlanRecord(
        source_key=build_plan_source_key("at", "textr", "AT 1GB 7Days", "1GB", 7, 0.99),
        destination_slug="at",
        destination_name="Austria",
        provider_slug="textr",
        provider_name="Textr eSIM",
        plan_name="AT 1GB 7Days",
        data_amount_text="1GB",
        data_amount_mb=1024,
        validity_days=7,
        price_amount=0.99,
        currency="USD",
        price_per_gb=0.99,
        coverage_type="5G",
        source_url="https://esimdb.com/austria/textr",
        last_seen_at=datetime.now(UTC),
    )
    repository.upsert_plan(stale)
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )
    with TestClient(app) as test_client:
        scrape_response = test_client.post(
            "/scrape",
            data={"destinations": "usa"},
            follow_redirects=True,
        )
        assert scrape_response.status_code == 200
        assert "Austria" not in scrape_response.text
        assert "USA 1GB 3Days" in scrape_response.text


def test_scrape_redirect_preserves_language(app_components) -> None:
    settings, repository = app_components
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )
    with TestClient(app) as test_client:
        response = test_client.post(
            "/scrape",
            data={"destinations": "usa", "lang": "zh"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "lang=zh" in response.headers["location"]


def test_upsert_plan_is_safe_for_duplicate_source_keys(app_components) -> None:
    _, repository = app_components
    assert isinstance(repository, Repository)

    source_key = build_plan_source_key("usa", "airalo", "USA 1GB 3Days", "1GB", 3, 1.0)
    first = PlanRecord(
        source_key=source_key,
        destination_slug="usa",
        destination_name="United States of America",
        provider_slug="airalo",
        provider_name="Airalo",
        plan_name="USA 1GB 3Days",
        data_amount_text="1GB",
        data_amount_mb=1024,
        validity_days=3,
        price_amount=1.0,
        currency="USD",
        price_per_gb=1.0,
        coverage_type="5G",
        source_url="https://esimdb.com/usa/airalo",
        last_seen_at=datetime.now(UTC),
    )
    second = PlanRecord(
        source_key=source_key,
        destination_slug="usa",
        destination_name="United States of America",
        provider_slug="airalo",
        provider_name="Airalo",
        plan_name="USA 1GB 3Days",
        data_amount_text="1GB",
        data_amount_mb=1024,
        validity_days=3,
        price_amount=1.0,
        currency="USD",
        price_per_gb=1.0,
        coverage_type="5G",
        source_url="https://esimdb.com/usa/airalo",
        last_seen_at=datetime.now(UTC),
    )

    assert repository.upsert_plan(first) == "inserted"
    assert repository.upsert_plan(second) in {"updated", "skipped"}


def test_async_scrape_start_endpoint_returns_immediately(app_components) -> None:
    settings, repository = app_components
    app = create_app(
        settings=settings,
        repository=repository,
        scraper_service=FakeScraperService(repository),
    )
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/scrape-start",
            data={"destinations": "usa", "lang": "en"},
        )
        assert response.status_code == 200
        assert response.json()["started"] is True


def test_repository_query_plans_supports_desc_sorting(app_components) -> None:
    _, repository = app_components

    cheap = PlanRecord(
        source_key=build_plan_source_key("usa", "airalo", "USA 1GB 3Days", "1GB", 3, 1.0),
        destination_slug="usa",
        destination_name="United States of America",
        provider_slug="airalo",
        provider_name="Airalo",
        plan_name="USA 1GB 3Days",
        data_amount_text="1GB",
        data_amount_mb=1024,
        validity_days=3,
        price_amount=1.0,
        currency="USD",
        price_per_gb=1.0,
        coverage_type="5G",
        source_url="https://esimdb.com/usa/airalo",
        last_seen_at=datetime.now(UTC),
    )
    expensive = PlanRecord(
        source_key=build_plan_source_key("usa", "bytesim", "USA 10GB 30Days", "10GB", 30, 9.0),
        destination_slug="usa",
        destination_name="United States of America",
        provider_slug="bytesim",
        provider_name="ByteSIM",
        plan_name="USA 10GB 30Days",
        data_amount_text="10GB",
        data_amount_mb=10240,
        validity_days=30,
        price_amount=9.0,
        currency="USD",
        price_per_gb=0.9,
        coverage_type="5G",
        source_url="https://esimdb.com/usa/bytesim",
        last_seen_at=datetime.now(UTC),
    )

    repository.upsert_plan(cheap)
    repository.upsert_plan(expensive)

    sorted_rows = repository.query_plans(PlanFilters(sort_by="price_amount", sort_order="desc"))

    assert sorted_rows[0]["price_amount"] == 9.0
    assert sorted_rows[1]["price_amount"] == 1.0


def test_build_export_filename_uses_destination_names() -> None:
    filename = build_export_filename(["United States of America"])
    assert filename.endswith("-United-States-of-America-EsimdbExport.csv")
    assert len(filename.split("-")[0]) == 10


def test_build_export_filename_uses_multiple_countries_marker() -> None:
    filename = build_export_filename(["United States of America", "Austria"])
    assert filename.endswith("-Multiple-Countries-EsimdbExport.csv")
