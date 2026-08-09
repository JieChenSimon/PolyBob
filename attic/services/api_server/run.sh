#!/bin/bash
set -e

echo "services/api_server is archived and no longer starts the trading API."
echo "Use the current core API entrypoint instead:"
echo "  python -m apps.api.main"
exit 1
