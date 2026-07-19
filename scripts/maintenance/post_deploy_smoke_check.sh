#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:5001}"
CANONICAL_URL="${2:-${MCLEOD_CANONICAL_CONTROL_CENTER_URL:-https://masons-imac.tailb88bd7.ts.net}}"
EXPECTED_CANONICAL_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-Desktop}"
EXPECTED_REPO_BASENAME="${MCLEOD_CANONICAL_REPO_BASENAME:-McLeod-Alpha-New}"
REQUIRE_BOT_RUNNING="${MCLEOD_SMOKE_REQUIRE_BOT_RUNNING:-0}"

python3 - <<'PY' "$BASE_URL" "$CANONICAL_URL" "$EXPECTED_CANONICAL_HOST" "$EXPECTED_REPO_BASENAME" "$REQUIRE_BOT_RUNNING"
import json
import ssl
import sys
import urllib.request

base_url = sys.argv[1].rstrip('/')
canonical_url = sys.argv[2].rstrip('/')
expected_host = sys.argv[3]
expected_repo = sys.argv[4]
require_bot = sys.argv[5] in {'1', 'true', 'yes', 'on'}

def fetch_json(url: str) -> dict:
    secure = url.startswith('https://')
    ctx = ssl._create_unverified_context() if secure else None
    req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))

def check_status(name: str, status: dict, failures: list[str]) -> None:
    if not status.get('status_schema_version'):
        failures.append(f"{name}: missing status_schema_version")
    if str(status.get('parity_state') or '').upper() != 'MATCH':
        failures.append(f"{name}: parity_state is {status.get('parity_state')}, expected MATCH")
    if bool(status.get('parity_block_start')):
        failures.append(f"{name}: parity_block_start is true")
    if status.get('runtime_host_is_canonical') is not True:
        failures.append(f"{name}: runtime_host_is_canonical is not true")
    if status.get('runtime_repo_path_ok') is not True:
        failures.append(f"{name}: runtime_repo_path_ok is not true")

    runtime_host = str((status.get('runtime_fingerprint') or {}).get('hostname') or '')
    if expected_host and runtime_host and runtime_host.lower() != expected_host.lower():
        failures.append(f"{name}: runtime host {runtime_host} != expected {expected_host}")

    runtime_repo = str(status.get('runtime_repo_basename') or '')
    if expected_repo and runtime_repo and runtime_repo.lower() != expected_repo.lower():
        failures.append(f"{name}: runtime repo {runtime_repo} != expected {expected_repo}")

    if require_bot and status.get('bot_running_effective') is not True:
        failures.append(f"{name}: bot_running_effective is not true")

failures: list[str] = []

base_status = fetch_json(base_url + '/api/status')
canonical_status = fetch_json(canonical_url + '/api/status')
today_trades = fetch_json(canonical_url + '/api/today-trades')

check_status('base', base_status, failures)
check_status('canonical', canonical_status, failures)

if today_trades.get('error'):
    failures.append(f"canonical: /api/today-trades error: {today_trades.get('error')}")

print(f"smoke_base_schema={base_status.get('status_schema_version')}")
print(f"smoke_canonical_schema={canonical_status.get('status_schema_version')}")
print(f"smoke_parity={canonical_status.get('parity_state')}")
print(f"smoke_repo_ok={canonical_status.get('runtime_repo_path_ok')}")
print(f"smoke_today_trades_count={len(today_trades.get('trades') or [])}")

if failures:
    print('smoke_status=FAILED')
    for item in failures:
        print(' - ' + item)
    raise SystemExit(1)

print('smoke_status=PASS')
PY
