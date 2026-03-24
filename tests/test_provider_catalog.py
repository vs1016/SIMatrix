from __future__ import annotations

import httpx

from app.provider_catalog import (
    fetch_remote_html,
    load_provider_catalog,
    provider_catalog_path,
    register_provider_from_url,
)


def test_register_provider_from_url_accepts_generic_provider_website(app_components, monkeypatch) -> None:
    settings, _ = app_components

    def fake_fetch_remote_html(resolved_settings, url: str) -> str:
        if url == "https://bytesim.com":
            return """
                <html>
                    <head>
                        <meta property="og:site_name" content="ByteSIM">
                        <meta property="og:image" content="/logo.png">
                        <title>ByteSIM</title>
                    </head>
                    <body>
                        <h1>ByteSIM</h1>
                    </body>
                </html>
            """
        if url == "https://esimdb.com/usa/bytesim":
            return """
                <html>
                    <body>
                        <h1>ByteSIM eSIM Data Plans for USA</h1>
                        <a href="https://bytesim.com">Official Website</a>
                        <img src="/assets/pictures/provider/bytesim_tiny.jpg" alt="ByteSIM">
                    </body>
                </html>
            """
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("app.provider_catalog.fetch_remote_html", fake_fetch_remote_html)
    monkeypatch.setattr("app.provider_catalog.cache_provider_logo", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "app.provider_catalog.load_provider_page_index",
        lambda resolved_settings: {
            "bytesim": "https://esimdb.com/usa/bytesim",
        },
    )

    provider = register_provider_from_url(settings, "https://bytesim.com")

    assert provider["provider_slug"] == "bytesim"
    assert provider["provider_name"] == "ByteSIM"
    assert provider["website_url"] == "https://bytesim.com"
    assert provider["official_website_url"] == "https://bytesim.com"


def test_register_provider_from_url_resolves_esimdb_slug_from_provider_name(app_components, monkeypatch) -> None:
    settings, _ = app_components

    def fake_fetch_remote_html(resolved_settings, url: str) -> str:
        if url == "https://acme.com":
            return """
                <html>
                    <head>
                        <meta property="og:site_name" content="Acme Mobile">
                    </head>
                    <body><h1>Acme Mobile</h1></body>
                </html>
            """
        if url == "https://esimdb.com/usa/acme-mobile":
            return """
                <html>
                    <body>
                        <h1>Acme Mobile eSIM Data Plans for USA</h1>
                        <a href="https://acme.com">Official Website</a>
                        <img src="/assets/pictures/provider/acme-mobile_tiny.jpg" alt="Acme Mobile">
                    </body>
                </html>
            """
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("app.provider_catalog.fetch_remote_html", fake_fetch_remote_html)
    monkeypatch.setattr(
        "app.provider_catalog.load_provider_page_index",
        lambda resolved_settings: {
            "acme-mobile": "https://esimdb.com/usa/acme-mobile",
        },
    )
    monkeypatch.setattr("app.provider_catalog.cache_provider_logo", lambda *args, **kwargs: True)

    provider = register_provider_from_url(settings, "https://acme.com")

    assert provider["provider_slug"] == "acme-mobile"
    assert provider["provider_name"] == "Acme Mobile"
    assert provider["website_url"] == "https://acme.com"
    assert provider["official_website_url"] == "https://acme.com"


def test_fetch_remote_html_falls_back_to_curl_when_httpx_is_blocked(app_components, monkeypatch) -> None:
    settings, _ = app_components

    class FakeResponse:
        status_code = 403

        def raise_for_status(self) -> None:
            request = httpx.Request("GET", "https://bytesim.com")
            raise httpx.HTTPStatusError("forbidden", request=request, response=self)

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str):
            return FakeResponse()

    class FakeCompletedProcess:
        returncode = 0
        stdout = "<html><title>ByteSIM</title></html>"
        stderr = ""

    monkeypatch.setattr("app.provider_catalog.httpx.Client", FakeClient)
    monkeypatch.setattr("app.provider_catalog.shutil.which", lambda name: "curl.exe")
    monkeypatch.setattr(
        "app.provider_catalog.subprocess.run",
        lambda *args, **kwargs: FakeCompletedProcess(),
    )

    html = fetch_remote_html(settings, "https://bytesim.com")

    assert "ByteSIM" in html


def test_load_provider_catalog_preserves_intentionally_empty_registry(app_components) -> None:
    settings, _ = app_components
    provider_catalog_path(settings).write_text("[]", encoding="utf-8")

    catalog = load_provider_catalog(settings)

    assert catalog == []
