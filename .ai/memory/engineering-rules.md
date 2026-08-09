# Engineering Rules

- The default Python environment for this project is the conda environment named `polybob`. Use that environment for Python commands, tests, and local service runs unless the user explicitly says otherwise.
- All provider HTTP goes through `libs/data/http_client.py` (bounded pooled session). Do not call `urllib.request.urlopen` directly: per-request connections leaked descriptors and, behind a system-wide proxy, kept the machine awake servicing TCP keepalives.
- A check that could not be run reports UNKNOWN, never PASS. "I did not look" and "I looked and it is clear" are different claims, and conflating them is the defect class this project keeps rediscovering.
