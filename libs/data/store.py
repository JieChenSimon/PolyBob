"""A bitemporal store: every row knows when it happened *and* when we learned it.

The problem this exists to solve is concrete. Re-running the insider experiment on
"the same" cached data produced n=753 one day and n=667 the next. Nothing in the
code changed. ``data/market_cache/`` held 613 JSON files that were overwritten on
every fetch and recorded no timestamp, so "the cache" was whatever the providers
last happened to return. An experiment whose sample size moves on its own cannot
support a promotion gate, however careful the statistics on top of it are.

Two dates, not one
------------------
Every row carries:

- ``event_date`` — when the thing happened in the market (the bar's session, the
  filing's date).
- ``fetched_at`` — when *we* first saw it.

That second column is the whole point. With it, "what did I know on 1 March?" is a
filter rather than an act of imagination, and a study can be replayed exactly:
:meth:`Store.read` with an ``as_of`` returns only rows we had actually observed by
then. Without it, every backtest silently uses restated, backfilled and
survivorship-cleaned data that did not exist at the time — the single most common
way a research result evaporates in production.

Look-ahead becomes inexpressible, not merely detectable
------------------------------------------------------
``libs/quant/pit.py`` already had look-ahead machinery, and it worked — but it was
referenced by nine test files and zero production modules. Protection that lives
in tests is a convention, and conventions get bypassed by the next piece of code
someone writes in a hurry. Here the guarantee is structural: a reader that passes
``as_of`` *cannot* obtain a row stamped later, because the filter runs inside the
store. This is the same choice Qlib makes by putting point-in-time semantics in
the storage layer rather than in the analysis layer.

Append-only
-----------
Writes never overwrite. Re-fetching a day that already exists appends a second
observation with a later ``fetched_at``; the reader takes the latest one at or
before its ``as_of``. So a provider silently restating history is *visible* —
you get two rows, with two dates — instead of destroying the old value.

Storage
-------
Parquet partitioned by dataset and symbol, queried with DuckDB. No server, no
schema migration, columnar scans over the whole history in milliseconds. This is
the standard local analytics stack and it is a good fit precisely because the
volumes here are small: 300MB of raw JSON becomes tens of MB of Parquet.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

STORE_ROOT = Path(os.environ.get("POLYBOB_STORE", "data/store"))

# The two temporal columns every dataset carries. Named here because a dataset
# that omits either one cannot be read point-in-time, and the writer rejects it
# rather than accepting a table that will quietly permit look-ahead later.
EVENT_DATE = "event_date"
FETCHED_AT = "fetched_at"

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class StoreError(RuntimeError):
    """A write that would make the store unreadable point-in-time."""


def _safe(name: str) -> str:
    return _SAFE.sub("_", str(name)).strip("_") or "unknown"


def _to_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value)[:10]
    return dt.date.fromisoformat(text)


def _to_utc(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)
    text = str(value).replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class Dataset:
    """A declared table. Datasets are named up front, not created on write.

    Registering a dataset is a decision about what the project measures, so it
    belongs in source rather than appearing because some script wrote to a new
    string. ``value_columns`` is what the reader can expect to find.
    """

    name: str
    value_columns: tuple[str, ...]
    description: str
    instrument_column: str = "symbol"
    effective_at_column: str = EVENT_DATE
    observed_at_column: str = FETCHED_AT
    pit_level: str = "collected_observation_time"
    price_basis: str = "not_applicable"
    strict_historical_pit: bool = False

    def path(self, symbol: str | None = None) -> Path:
        base = STORE_ROOT / _safe(self.name)
        return base if symbol is None else base / f"symbol={_safe(symbol)}"

    def contract(self) -> dict[str, Any]:
        """Machine-readable time and price semantics for this dataset.

        ``collected_observation_time`` is intentionally narrower than
        ``historical_point_in_time``: the store can replay vintages observed since
        collection began, but a history first downloaded today does not become
        knowledge that existed years ago merely because its event dates are old.
        """
        return {
            "dataset": self.name,
            "instrument": self.instrument_column,
            "effective_at": self.effective_at_column,
            "observed_at": self.observed_at_column,
            "pit_level": self.pit_level,
            "strict_historical_pit": self.strict_historical_pit,
            "price_basis": self.price_basis,
            "value_columns": list(self.value_columns),
        }


DAILY_BARS = Dataset(
    "daily_bars",
    ("open", "high", "low", "close", "volume", "source", "price_basis"),
    "日线 OHLCV。缺失的字段保持 None,不用 close 顶替、不填 0。",
    price_basis="row_declared",
)
FUNDING_RATES = Dataset(
    "funding_rates", ("rate", "source"),
    "永续资金费(日均)。做空腿的收益必须含它,所以缺失就是不可测,不是 0。",
)
INSIDER_FILINGS = Dataset(
    "insider_filings",
    ("symbol_reported", "insider", "transaction_date", "value_usd", "is_open_market_buy", "source"),
    "SEC Form 345 申报。event_date 用 filing_date(公开披露日),不是成交日。",
)
POSITIONING = Dataset(
    "positioning", ("long_short_ratio", "source"),
    "交易所公布的多空账户比。",
)
CORPORATE_ACTIONS = Dataset(
    "corporate_actions",
    (
        "action_type", "ratio", "cash_amount", "currency", "source",
        "price_basis_before", "price_basis_after",
    ),
    "公司行动。event_date 是行动生效日；拆股 ratio 是每一旧股获得的新股数量。",
    price_basis="action_declared",
)

DATASETS: tuple[Dataset, ...] = (
    DAILY_BARS,
    FUNDING_RATES,
    INSIDER_FILINGS,
    POSITIONING,
    CORPORATE_ACTIONS,
)


def dataset(name: str) -> Dataset:
    for d in DATASETS:
        if d.name == name:
            return d
    raise KeyError(f"unknown dataset '{name}'; declared: {', '.join(d.name for d in DATASETS)}")


def dataset_contracts() -> dict[str, dict[str, Any]]:
    """Return every declared dataset contract keyed by dataset name."""
    return {declared.name: declared.contract() for declared in DATASETS}


def _payload_digest(ds: Dataset, symbol: str, records: Sequence[dict[str, Any]]) -> str:
    """Stable identity for one provider payload, excluding observation time."""

    def encode(value: Any) -> Any:
        if isinstance(value, (dt.datetime, dt.date)):
            return value.isoformat()
        if hasattr(value, "item"):
            try:
                return value.item()
            except (TypeError, ValueError):
                pass
        return value

    canonical_rows = [
        {
            key: encode(value)
            for key, value in sorted(record.items())
            if key != FETCHED_AT
        }
        for record in records
    ]
    canonical_rows.sort(
        key=lambda row: (str(row.get(EVENT_DATE, "")), str(row.get(ds.instrument_column, symbol)))
    )
    payload = {
        "dataset": ds.name,
        "instrument": symbol,
        "rows": canonical_rows,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


# --------------------------------------------------------------------- writing


def write(
    ds: Dataset | str,
    symbol: str,
    rows: Sequence[dict[str, Any]],
    *,
    fetched_at: dt.datetime | None = None,
    deduplicate_payload: bool = False,
) -> int:
    """Append observations without overwriting an earlier data vintage.

    Each distinct observation writes one Parquet file stamped with a single
    ``fetched_at``. If the same ``event_date`` was already stored with changed
    content, both rows survive: the reader resolves
    to the latest observation at or before its ``as_of``, so a provider restating
    the past becomes something you can see and measure rather than a silent edit
    to your own history. Provider mirrors may opt into payload idempotency: an
    identical full payload is then a retry/cache hit rather than a new vintage,
    while any content change still appends a distinct observation.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    ds = ds if isinstance(ds, Dataset) else dataset(ds)
    if not rows:
        return 0

    stamp = _to_utc(fetched_at or now_utc())
    records: list[dict[str, Any]] = []
    for row in rows:
        if EVENT_DATE not in row:
            raise StoreError(
                f"{ds.name}: every row needs '{EVENT_DATE}'. Without it the row "
                "cannot be placed in time, and a table that cannot be read "
                "point-in-time is exactly what this store replaced."
            )
        record = {k: v for k, v in row.items() if k != FETCHED_AT}
        record[EVENT_DATE] = _to_date(record[EVENT_DATE]).isoformat()
        record[FETCHED_AT] = stamp
        records.append(record)

    target = ds.path(symbol)
    target.mkdir(parents=True, exist_ok=True)
    if deduplicate_payload:
        # A content-addressed filename is the cross-process idempotency key. Each
        # writer first creates a private Parquet file and then atomically links it
        # into place; exactly one concurrent writer can win, and the winner's
        # fetched_at remains the first local observation of this payload.
        digest = _payload_digest(ds, symbol, records)
        destination = target / f"payload-{digest}.parquet"
        if destination.exists():
            return 0
        pending: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target, prefix=".pending-", suffix=".parquet", delete=False
            ) as handle:
                pending = Path(handle.name)
            pq.write_table(pa.Table.from_pylist(records), pending, compression="zstd")
            try:
                os.link(pending, destination)
            except FileExistsError:
                return 0
            return len(records)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)

    # Filename carries the observation time, so the partition is self-describing
    # and two fetches in the same second still land in different files.
    name = f"{stamp.strftime('%Y%m%dT%H%M%S%f')}.parquet"
    pq.write_table(pa.Table.from_pylist(records), target / name, compression="zstd")
    return len(records)


# --------------------------------------------------------------------- reading


# One DuckDB connection, reused. It is in-process and stateless for our purposes —
# every query names its own parquet files — so a fresh connection per call bought
# nothing and cost a great deal: the live scanner reads one symbol at a time, and the
# validation harness issued ~100k connections before this was noticed. Connections are
# cheap individually and ruinous in aggregate, which is the usual shape of this bug.
_CONNECTION: Any = None


def _connect():
    global _CONNECTION
    if _CONNECTION is None:
        import duckdb

        _CONNECTION = duckdb.connect()
    return _CONNECTION


def close() -> None:
    """Release the shared connection. Tests that swap ``STORE_ROOT`` do not need
    this — the connection holds no reference to a directory — but a long-lived
    process shutting down should."""
    global _CONNECTION
    if _CONNECTION is not None:
        try:
            _CONNECTION.close()
        finally:
            _CONNECTION = None


def _files(ds: Dataset, symbols: Iterable[str] | None) -> list[str]:
    base = ds.path()
    if not base.exists():
        return []
    if symbols is None:
        return [str(p) for p in sorted(base.rglob("*.parquet"))]
    out: list[str] = []
    for symbol in symbols:
        out.extend(str(p) for p in sorted(ds.path(symbol).glob("*.parquet")))
    return out


def read(
    ds: Dataset | str,
    symbols: Iterable[str] | str | None = None,
    *,
    as_of: dt.datetime | dt.date | None = None,
    start: dt.date | str | None = None,
    end: dt.date | str | None = None,
):
    """Rows as they were known at ``as_of``, one per (symbol, event_date).

    ``as_of=None`` means "everything currently stored", which is the right default
    for a live scan — today you genuinely do know the latest values. An experiment
    must always pass one: that is what makes its result reproducible, and
    :func:`libs.data.run_manifest.pin` exists to record which one it used.

    Returns a pandas DataFrame. Empty (with the right columns) when nothing
    matches, so callers never have to distinguish "no data" from "no table".
    """
    import pandas as pd

    ds = ds if isinstance(ds, Dataset) else dataset(ds)
    if isinstance(symbols, str):
        symbols = [symbols]
    files = _files(ds, symbols)
    columns = ["symbol", EVENT_DATE, FETCHED_AT, *ds.value_columns]
    if not files:
        return pd.DataFrame({c: [] for c in columns})

    conditions = []
    params: list[Any] = []
    if as_of is not None:
        conditions.append(f"{FETCHED_AT} <= ?")
        params.append(_to_utc(as_of))
    if start is not None:
        conditions.append(f"{EVENT_DATE} >= ?")
        params.append(_to_date(start).isoformat())
    if end is not None:
        conditions.append(f"{EVENT_DATE} <= ?")
        params.append(_to_date(end).isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # The window keeps the latest observation of each (symbol, event_date) that
    # existed at ``as_of``. This single expression is the point-in-time guarantee:
    # a caller cannot reach a later restatement, because the filter is applied
    # before the pick, inside the store.
    sql = f"""
        WITH observed AS (
            SELECT *, row_number() OVER (
                PARTITION BY symbol, {EVENT_DATE} ORDER BY {FETCHED_AT} DESC
            ) AS _rank
            FROM read_parquet(?, union_by_name = true, hive_partitioning = true)
            {where}
        )
        SELECT * EXCLUDE (_rank) FROM observed WHERE _rank = 1
        ORDER BY symbol, {EVENT_DATE}
    """
    frame = _connect().execute(sql, [files, *params]).df()
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    return frame


def restatements(ds: Dataset | str, symbols: Iterable[str] | str | None = None):
    """Event dates that were observed more than once with a different value.

    A provider quietly changing history is a research risk that the old
    overwrite-in-place cache made invisible. Here it is a query, so "how much of
    my sample was restated after the fact?" has an answer.
    """
    import pandas as pd

    ds = ds if isinstance(ds, Dataset) else dataset(ds)
    if isinstance(symbols, str):
        symbols = [symbols]
    files = _files(ds, symbols)
    if not files:
        return pd.DataFrame({"symbol": [], EVENT_DATE: [], "observations": []})
    return _connect().execute(
        f"""
        SELECT symbol, {EVENT_DATE}, count(*) AS observations,
               min({FETCHED_AT}) AS first_seen, max({FETCHED_AT}) AS last_seen
        FROM read_parquet(?, union_by_name = true, hive_partitioning = true)
        GROUP BY symbol, {EVENT_DATE}
        HAVING count(*) > 1
        ORDER BY observations DESC, symbol, {EVENT_DATE}
        """,
        [files],
    ).df()


def coverage(ds: Dataset | str) -> dict[str, Any]:
    """What the store actually holds — for a page that must not overstate itself."""
    ds = ds if isinstance(ds, Dataset) else dataset(ds)
    files = _files(ds, None)
    if not files:
        return {"dataset": ds.name, "symbols": 0, "rows": 0, "start": None, "end": None,
                "first_fetch": None, "last_fetch": None}
    row = _connect().execute(
        f"""
        SELECT count(DISTINCT symbol), count(*), min({EVENT_DATE}), max({EVENT_DATE}),
               min({FETCHED_AT}), max({FETCHED_AT})
        FROM read_parquet(?, union_by_name = true, hive_partitioning = true)
        """,
        [files],
    ).fetchone()
    return {
        "dataset": ds.name, "symbols": row[0], "rows": row[1],
        "start": row[2], "end": row[3],
        "first_fetch": str(row[4]) if row[4] else None,
        "last_fetch": str(row[5]) if row[5] else None,
    }


def symbols(ds: Dataset | str) -> list[str]:
    ds = ds if isinstance(ds, Dataset) else dataset(ds)
    base = ds.path()
    if not base.exists():
        return []
    return sorted(
        p.name.split("=", 1)[1] for p in base.iterdir()
        if p.is_dir() and p.name.startswith("symbol=")
    )


__all__ = [
    "CORPORATE_ACTIONS", "DAILY_BARS", "DATASETS", "EVENT_DATE", "FETCHED_AT", "FUNDING_RATES",
    "INSIDER_FILINGS", "POSITIONING", "STORE_ROOT", "Dataset", "StoreError",
    "close", "coverage", "dataset", "dataset_contracts", "now_utc", "read", "restatements", "symbols",
    "write",
]
