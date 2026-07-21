#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:5001}"

python3 - <<'PY' "$BASE_URL"
import json
import ssl
import sys
import urllib.request

base = sys.argv[1].rstrip('/')
secure = base.startswith('https://')
ctx = ssl._create_unverified_context() if secure else None

with urllib.request.urlopen(base + '/api/status', context=ctx, timeout=20) as r:
    status = json.loads(r.read().decode())

fp = status.get('runtime_fingerprint') or {}
print('base_url:', base)
print('parity_state:', status.get('parity_state'))
print('parity_block_start:', status.get('parity_block_start'))
print('parity_issues:', status.get('parity_issues'))
print('runtime_hostname:', fp.get('hostname'))
print('project_root:', fp.get('project_root'))
print('python_executable:', fp.get('python_executable'))
print('cockpit_sha256:', fp.get('cockpit_sha256'))
print('bot_script_sha256:', fp.get('bot_script_sha256'))
print('dependency_hash:', fp.get('dependency_hash'))
print('bot_running:', status.get('bot_running'))
print('bot_running_effective:', status.get('bot_running_effective'))
print('trade_entry_reason:', status.get('trade_entry_reason'))
PY

echo "\nlocal_git_status:"
if git -C "$(cd "$(dirname "$0")/../.." && pwd)" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$(cd "$(dirname "$0")/../.." && pwd)" status --short | sed -n '1,20p'
else
  echo "(not a git repo)"
fi
