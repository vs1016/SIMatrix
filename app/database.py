from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_database(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")
    connection.execute("PRAGMA temp_store = MEMORY;")
    connection.execute("PRAGMA cache_size = -64000;")
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL UNIQUE,
            destination_slug TEXT NOT NULL,
            destination_name TEXT NOT NULL,
            provider_slug TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            plan_name TEXT NOT NULL,
            data_amount_text TEXT NOT NULL,
            data_amount_mb REAL,
            validity_days INTEGER,
            price_amount REAL,
            currency TEXT NOT NULL DEFAULT 'USD',
            price_per_gb REAL,
            coverage_type TEXT,
            source_url TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_plans_destination ON plans(destination_slug);
        CREATE INDEX IF NOT EXISTS idx_plans_provider ON plans(provider_slug);
        CREATE INDEX IF NOT EXISTS idx_plans_price ON plans(price_amount);
        CREATE INDEX IF NOT EXISTS idx_plans_price_per_gb ON plans(price_per_gb);
        CREATE INDEX IF NOT EXISTS idx_plans_validity ON plans(validity_days);
        CREATE INDEX IF NOT EXISTS idx_plans_data_mb ON plans(data_amount_mb);
        CREATE INDEX IF NOT EXISTS idx_plans_provider_name ON plans(provider_name);
        CREATE INDEX IF NOT EXISTS idx_plans_destination_name ON plans(destination_name);
        CREATE INDEX IF NOT EXISTS idx_plans_plan_name ON plans(plan_name);
        CREATE INDEX IF NOT EXISTS idx_plans_filter_sort ON plans(destination_slug, provider_slug, price_amount, provider_name, plan_name);

        CREATE TABLE IF NOT EXISTS scrape_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            status TEXT NOT NULL,
            destination_slugs TEXT NOT NULL,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            updated_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT
        );
        """
    )
    connection.commit()
