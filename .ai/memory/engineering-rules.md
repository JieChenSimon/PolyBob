# Engineering Rules

- Python dependencies are managed only by `uv` from `pyproject.toml` and committed `uv.lock`; use `uv run --locked` for Python commands and the project-local `.venv`. Do not add a parallel Conda or requirements-file dependency source.
- All provider HTTP goes through `libs/data/http_client.py` (bounded pooled session). Do not call `urllib.request.urlopen` directly: per-request connections leaked descriptors and, behind a system-wide proxy, kept the machine awake servicing TCP keepalives.
- A check that could not be run reports UNKNOWN, never PASS. "I did not look" and "I looked and it is clear" are different claims, and conflating them is the defect class this project keeps rediscovering.
