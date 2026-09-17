#!/usr/bin/env bash
# Verify PEXELS_API_KEY from repo-root .env or the environment. Does not print the key.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${PEXELS_API_KEY:-}" && -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

if [[ -z "${PEXELS_API_KEY:-}" ]]; then
  echo "ERROR: PEXELS_API_KEY is empty. Put it in .env or export it first." >&2
  exit 1
fi

echo "Calling Pexels search API (query=coffee, per_page=1)..."
HTTP_CODE=$(curl -sS -o /tmp/pexels_verify_$$.json -w "%{http_code}" \
  -H "Authorization: ${PEXELS_API_KEY}" \
  "https://api.pexels.com/v1/search?query=coffee&per_page=1")

echo "HTTP status: ${HTTP_CODE}"
if [[ "${HTTP_CODE}" != "200" ]]; then
  echo "Body (truncated):"
  head -c 400 "/tmp/pexels_verify_$$.json"; echo
  rm -f "/tmp/pexels_verify_$$.json"
  exit 1
fi

python3 - <<'PY'
import json
from pathlib import Path
import glob
paths = sorted(glob.glob('/tmp/pexels_verify_*.json'))
data = json.loads(Path(paths[-1]).read_text())
photos = data.get('photos') or []
print(f"OK: total_results={data.get('total_results')} returned={len(photos)}")
if photos:
    p = photos[0]
    print(f"sample_id={p.get('id')} photographer={p.get('photographer')}")
    print(f"url={p.get('url')}")
PY
rm -f /tmp/pexels_verify_$$.json
echo "Done. Key was not printed."
