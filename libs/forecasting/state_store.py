"""Persistent per-instrument controls for the opt-in forecasting lab."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from libs.db import fact_store


SUPPORTED_DOMAINS = frozenset({"crypto_spot", "us_equity", "a_share"})

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS forecast_instrument_settings (
    domain TEXT NOT NULL,
    symbol TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    horizon INTEGER NOT NULL DEFAULT 5 CHECK (horizon BETWEEN 1 AND 20),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (domain, symbol)
)
"""


def normalize_instrument(domain: str, symbol: str) -> tuple[str, str]:
    clean_domain = domain.strip().lower()
    clean_symbol = symbol.strip().upper()
    if clean_domain not in SUPPORTED_DOMAINS:
        raise ValueError(f"unsupported forecast domain: {clean_domain}")
    if not clean_symbol or len(clean_symbol) > 40:
        raise ValueError("symbol must contain 1-40 characters")
    return clean_domain, clean_symbol


@dataclass(frozen=True)
class ForecastInstrumentSetting:
    domain: str
    symbol: str
    enabled: bool
    horizon: int
    updated_at: str | None

    def to_dict(self) -> dict:
        return asdict(self)


class ForecastInstrumentStore:
    """SQLite-backed allowlist; missing rows are disabled by definition."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = fact_store._resolve_db_path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self):
        connection = fact_store.connect(fact_store._ensure_schema(self._db_path))
        connection.execute(_CREATE_TABLE)
        return connection

    def get(self, domain: str, symbol: str) -> ForecastInstrumentSetting:
        domain, symbol = normalize_instrument(domain, symbol)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT domain, symbol, enabled, horizon, updated_at
                FROM forecast_instrument_settings
                WHERE domain = ? AND symbol = ?
                """,
                (domain, symbol),
            ).fetchone()
        if row is None:
            return ForecastInstrumentSetting(domain, symbol, False, 5, None)
        return ForecastInstrumentSetting(
            domain=row["domain"],
            symbol=row["symbol"],
            enabled=bool(row["enabled"]),
            horizon=int(row["horizon"]),
            updated_at=row["updated_at"],
        )

    def set(
        self, domain: str, symbol: str, *, enabled: bool, horizon: int
    ) -> ForecastInstrumentSetting:
        domain, symbol = normalize_instrument(domain, symbol)
        if not 1 <= int(horizon) <= 20:
            raise ValueError("horizon must be between 1 and 20")
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forecast_instrument_settings
                    (domain, symbol, enabled, horizon, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(domain, symbol) DO UPDATE SET
                    enabled = excluded.enabled,
                    horizon = excluded.horizon,
                    updated_at = excluded.updated_at
                """,
                (domain, symbol, int(enabled), int(horizon), now),
            )
            connection.execute(
                """
                INSERT INTO audit_events
                    (event_type, actor, subject_type, subject_id, payload_json, created_at)
                VALUES ('forecast.instrument_configured', 'operator',
                        'forecast_instrument', ?, ?, ?)
                """,
                (
                    f"{domain}:{symbol}",
                    json.dumps(
                        {"enabled": bool(enabled), "horizon": int(horizon)},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    now,
                ),
            )
        return ForecastInstrumentSetting(domain, symbol, bool(enabled), int(horizon), now)

    def list_enabled(self, domain: str | None = None) -> list[ForecastInstrumentSetting]:
        params: tuple[str, ...] = ()
        where = "WHERE enabled = 1"
        if domain is not None:
            clean_domain, _ = normalize_instrument(domain, "VALIDATION")
            where += " AND domain = ?"
            params = (clean_domain,)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT domain, symbol, enabled, horizon, updated_at
                FROM forecast_instrument_settings
                {where}
                ORDER BY domain, symbol
                """,
                params,
            ).fetchall()
        return [
            ForecastInstrumentSetting(
                domain=row["domain"],
                symbol=row["symbol"],
                enabled=True,
                horizon=int(row["horizon"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
