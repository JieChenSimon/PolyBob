"""Archived API entrypoint.

This module is intentionally not a runnable trading API. Use apps.api.main for
the current core workbench server.
"""
from datetime import datetime

from fastapi import FastAPI


ARCHIVE_MESSAGE = (
    "services/api_server is archived and no longer exposes trading API routes. "
    "Start the current API with: python -m apps.api.main"
)

app = FastAPI(title="PolyBob Archived API", description=ARCHIVE_MESSAGE)


def archive_payload() -> dict:
    return {
        "status": "archived",
        "service": "services/api_server",
        "message": ARCHIVE_MESSAGE,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/")
async def root():
    return archive_payload()


@app.get("/health")
async def health():
    return archive_payload()


if __name__ == "__main__":
    raise RuntimeError(ARCHIVE_MESSAGE)
