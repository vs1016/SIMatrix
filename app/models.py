from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class PlanRecord:
    source_key: str
    destination_slug: str
    destination_name: str
    provider_slug: str
    provider_name: str
    plan_name: str
    data_amount_text: str
    data_amount_mb: float | None
    validity_days: int | None
    price_amount: float | None
    currency: str
    price_per_gb: float | None
    coverage_type: str | None
    source_url: str
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class PlanFilters:
    destination_slug: str = ""
    provider_slug: str = ""
    min_price: float | None = None
    max_price: float | None = None
    min_validity_days: int | None = None
    min_data_mb: float | None = None
    sort_by: str = "price_amount"
    sort_order: str = "asc"


@dataclass(slots=True)
class ScrapeRunSummary:
    id: int
    status: str
    started_at: str
    finished_at: str | None
    destination_slugs: str
    inserted_count: int
    updated_count: int
    skipped_count: int
    error_summary: str | None
