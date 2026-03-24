from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import connect_database, initialize_database
from app.main import create_app
from app.repository import Repository


@pytest.fixture()
def app_components():
    tmp_root = Path(__file__).resolve().parents[1] / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(tempfile.mkdtemp(prefix="rtg-tests-", dir=tmp_root))
    database_path = Path(__file__).resolve().parents[1] / f"test-{uuid4().hex}.sqlite3"
    settings = Settings(
        base_url="https://esimdb.com",
        project_root=Path(__file__).resolve().parents[1],
        data_dir=tmp_path,
        database_path=database_path,
        flag_icon_dir=Path(__file__).resolve().parents[1] / "icon",
        provider_icon_dir=tmp_path / "provider-icons",
        supported_destinations=("usa",),
        preset_provider_slugs=(
            "airalo",
            "nomad",
            "textr",
            "billionconnect",
            "bytesim",
        ),
        destination_match_mode="strict",
        max_providers_per_destination=1,
        provider_fetch_workers=4,
        http_timeout_seconds=5,
        user_agent="pytest-agent",
    )
    settings.ensure_directories()
    connection = connect_database(database_path)
    initialize_database(connection)
    repository = Repository(connection)
    yield settings, repository
    connection.close()
    if database_path.exists():
        database_path.unlink()
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture()
def client(app_components):
    settings, repository = app_components
    app = create_app(settings=settings, repository=repository)
    with TestClient(app) as test_client:
        yield test_client, repository
