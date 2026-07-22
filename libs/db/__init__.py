"""Local SQLite fact store helpers and pluggable storage backends."""

from libs.db.fact_store import (
    append_audit_event,
    append_audit_events,
    bootstrap,
    close_writer_connections,
    connect,
    init_db,
)
from libs.db.storage import (
    PostgresStorageBackend,
    SQLiteStorageBackend,
    StorageBackend,
    build_storage_backend,
    open_storage_backend,
    resolve_backend_name,
)

__all__ = [
    "append_audit_event",
    "append_audit_events",
    "bootstrap",
    "close_writer_connections",
    "connect",
    "init_db",
    "PostgresStorageBackend",
    "SQLiteStorageBackend",
    "StorageBackend",
    "build_storage_backend",
    "open_storage_backend",
    "resolve_backend_name",
]
