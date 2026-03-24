from __future__ import annotations

from contextlib import contextmanager
import csv
import hashlib
import io
import sqlite3
from datetime import UTC, datetime
from typing import Iterable

from app.models import PlanFilters, PlanRecord, ScrapeRunSummary
from app.presentation import sanitize_plan_display_name


def build_plan_source_key(
    destination_slug: str,
    provider_slug: str,
    plan_name: str,
    data_amount_text: str,
    validity_days: int | None,
    price_amount: float | None,
) -> str:
    raw_key = "|".join(
        [
            destination_slug.strip().lower(),
            provider_slug.strip().lower(),
            plan_name.strip().lower(),
            data_amount_text.strip().lower(),
            str(validity_days or ""),
            f"{price_amount:.4f}" if price_amount is not None else "",
        ]
    )
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class Repository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._transaction_depth = 0

    @contextmanager
    def transaction(self):
        is_outermost = self._transaction_depth == 0
        if is_outermost:
            self.connection.execute("BEGIN")
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_depth -= 1
            if is_outermost:
                self.connection.rollback()
            raise
        else:
            self._transaction_depth -= 1
            if is_outermost:
                self.connection.commit()

    def _maybe_commit(self) -> None:
        if self._transaction_depth == 0:
            self.connection.commit()

    def clear_plans(self) -> None:
        self.connection.execute("DELETE FROM plans")
        self._maybe_commit()

    def create_scrape_run(self, destination_slugs: Iterable[str]) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO scrape_runs(status, destination_slugs)
            VALUES(?, ?)
            """,
            ("running", ",".join(destination_slugs)),
        )
        self._maybe_commit()
        return int(cursor.lastrowid)

    def finish_scrape_run(
        self,
        run_id: int,
        *,
        status: str,
        inserted_count: int,
        updated_count: int,
        skipped_count: int,
        error_summary: str | None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE scrape_runs
            SET finished_at = CURRENT_TIMESTAMP,
                status = ?,
                inserted_count = ?,
                updated_count = ?,
                skipped_count = ?,
                error_summary = ?
            WHERE id = ?
            """,
            (status, inserted_count, updated_count, skipped_count, error_summary, run_id),
        )
        self._maybe_commit()

    def latest_scrape_run(self) -> ScrapeRunSummary | None:
        row = self.connection.execute(
            """
            SELECT id, status, started_at, finished_at, destination_slugs,
                   inserted_count, updated_count, skipped_count, error_summary
            FROM scrape_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return ScrapeRunSummary(
            id=row["id"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            destination_slugs=row["destination_slugs"],
            inserted_count=row["inserted_count"],
            updated_count=row["updated_count"],
            skipped_count=row["skipped_count"],
            error_summary=row["error_summary"],
        )

    def prune_provider_destination_plans(
        self,
        destination_slug: str,
        provider_slug: str,
        valid_source_keys: set[str],
    ) -> None:
        if valid_source_keys:
            placeholders = ",".join("?" for _ in valid_source_keys)
            params = [destination_slug, provider_slug, *sorted(valid_source_keys)]
            self.connection.execute(
                f"""
                DELETE FROM plans
                WHERE destination_slug = ?
                  AND provider_slug = ?
                  AND source_key NOT IN ({placeholders})
                """,
                params,
            )
        else:
            self.connection.execute(
                """
                DELETE FROM plans
                WHERE destination_slug = ?
                  AND provider_slug = ?
                """,
                (destination_slug, provider_slug),
            )
        self._maybe_commit()

    def upsert_plan(self, plan: PlanRecord) -> str:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        insert_cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO plans(
                source_key, destination_slug, destination_name,
                provider_slug, provider_name, plan_name,
                data_amount_text, data_amount_mb, validity_days,
                price_amount, currency, price_per_gb, coverage_type,
                source_url, last_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.source_key,
                plan.destination_slug,
                plan.destination_name,
                plan.provider_slug,
                plan.provider_name,
                plan.plan_name,
                plan.data_amount_text,
                plan.data_amount_mb,
                plan.validity_days,
                plan.price_amount,
                plan.currency,
                plan.price_per_gb,
                plan.coverage_type,
                plan.source_url,
                plan.last_seen_at.isoformat(timespec="seconds"),
                now,
            ),
        )
        if insert_cursor.rowcount == 1:
            self._maybe_commit()
            return "inserted"

        existing = self.connection.execute(
            "SELECT * FROM plans WHERE source_key = ?", (plan.source_key,)
        ).fetchone()
        if existing is None:
            self._maybe_commit()
            return "skipped"

        changed = any(
            [
                existing["destination_name"] != plan.destination_name,
                existing["provider_name"] != plan.provider_name,
                existing["data_amount_text"] != plan.data_amount_text,
                existing["data_amount_mb"] != plan.data_amount_mb,
                existing["validity_days"] != plan.validity_days,
                existing["price_amount"] != plan.price_amount,
                existing["currency"] != plan.currency,
                existing["price_per_gb"] != plan.price_per_gb,
                existing["coverage_type"] != plan.coverage_type,
                existing["source_url"] != plan.source_url,
            ]
        )
        self.connection.execute(
            """
            UPDATE plans
            SET destination_name = ?,
                provider_name = ?,
                plan_name = ?,
                data_amount_text = ?,
                data_amount_mb = ?,
                validity_days = ?,
                price_amount = ?,
                currency = ?,
                price_per_gb = ?,
                coverage_type = ?,
                source_url = ?,
                last_seen_at = ?,
                updated_at = ?
            WHERE source_key = ?
            """,
            (
                plan.destination_name,
                plan.provider_name,
                plan.plan_name,
                plan.data_amount_text,
                plan.data_amount_mb,
                plan.validity_days,
                plan.price_amount,
                plan.currency,
                plan.price_per_gb,
                plan.coverage_type,
                plan.source_url,
                plan.last_seen_at.isoformat(timespec="seconds"),
                now,
                plan.source_key,
            ),
        )
        self._maybe_commit()
        return "updated" if changed else "skipped"

    def query_plans(self, filters: PlanFilters) -> list[sqlite3.Row]:
        sortable_columns = {
            "provider_name": "provider_name",
            "destination_name": "destination_name",
            "plan_name": "plan_name",
            "data_amount_mb": "data_amount_mb",
            "validity_days": "validity_days",
            "price_amount": "price_amount",
            "price_per_gb": "price_per_gb",
        }
        sort_column = sortable_columns.get(filters.sort_by, "price_amount")
        sort_order = "DESC" if filters.sort_order.lower() == "desc" else "ASC"
        query = """
            SELECT *
            FROM plans
            WHERE 1 = 1
        """
        params: list[object] = []
        if filters.destination_slug:
            query += " AND destination_slug = ?"
            params.append(filters.destination_slug)
        if filters.provider_slug:
            query += " AND provider_slug = ?"
            params.append(filters.provider_slug)
        if filters.min_price is not None:
            query += " AND price_amount >= ?"
            params.append(filters.min_price)
        if filters.max_price is not None:
            query += " AND price_amount <= ?"
            params.append(filters.max_price)
        if filters.min_validity_days is not None:
            query += " AND validity_days >= ?"
            params.append(filters.min_validity_days)
        if filters.min_data_mb is not None:
            query += " AND data_amount_mb >= ?"
            params.append(filters.min_data_mb)
        query += f" ORDER BY {sort_column} {sort_order}, provider_name ASC, plan_name ASC"
        return list(self.connection.execute(query, params).fetchall())

    def list_destinations(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT destination_slug, destination_name, COUNT(*) AS plan_count
                FROM plans
                GROUP BY destination_slug, destination_name
                ORDER BY destination_name ASC
                """
            ).fetchall()
        )

    def list_providers(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT provider_slug, provider_name, COUNT(*) AS plan_count
                FROM plans
                GROUP BY provider_slug, provider_name
                ORDER BY provider_name ASC
                """
            ).fetchall()
        )

    def export_csv(self, filters: PlanFilters) -> str:
        rows = self.query_plans(filters)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "destination_slug",
                "destination_name",
                "provider_slug",
                "provider_name",
                "display_plan_name",
                "raw_plan_name",
                "data_amount_text",
                "data_amount_mb",
                "validity_days",
                "price_amount",
                "currency",
                "price_per_gb",
                "coverage_type",
                "source_url",
                "last_seen_at",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["destination_slug"],
                    row["destination_name"],
                    row["provider_slug"],
                    row["provider_name"],
                    sanitize_plan_display_name(row["plan_name"]),
                    row["plan_name"],
                    row["data_amount_text"],
                    row["data_amount_mb"],
                    row["validity_days"],
                    row["price_amount"],
                    row["currency"],
                    row["price_per_gb"],
                    row["coverage_type"],
                    row["source_url"],
                    row["last_seen_at"],
                ]
            )
        return output.getvalue()
