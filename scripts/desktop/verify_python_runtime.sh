#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
VENV_PY="$ROOT_DIR/.venv/bin/python"
EXPECTED="$VENV_PY"

if [[ ! -x "$VENV_PY" ]]; then
  echo "ERROR: missing preferred runtime: $VENV_PY"
  exit 2
fi

current_py=$(command -v python3 || true)
venv_ver=$($VENV_PY -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')

printf "Preferred runtime: %s\n" "$EXPECTED"
printf "Preferred version: %s\n" "$venv_ver"
printf "Shell python3: %s\n" "${current_py:-none}"

# Verify key dependencies used by bot stack are importable in standardized runtime.
$VENV_PY - <<'PY'
import importlib.util
mods = ["pandas", "dotenv", "requests", "schwab"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
if missing:
    print("ERROR: missing modules in .venv: " + ",".join(missing))
    raise SystemExit(2)
print("Runtime import verification: OK")
PY
