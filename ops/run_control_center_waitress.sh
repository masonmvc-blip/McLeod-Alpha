#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN=""

python_has_waitress() {
	local py="$1"
	"$py" -c 'import flask, waitress' >/dev/null 2>&1
}

for candidate in \
	"/opt/homebrew/opt/python@3.11/bin/python3.11" \
	"$PROJECT_DIR/.venv/bin/python3" \
	"$PROJECT_DIR/venv/bin/python3" \
	"/opt/homebrew/bin/python3" \
	"python3"; do
	if [[ "$candidate" == "python3" ]]; then
		if command -v python3 >/dev/null 2>&1 && python_has_waitress "$(command -v python3)"; then
			PYTHON_BIN="$(command -v python3)"
			break
		fi
	elif [[ -x "$candidate" ]] && python_has_waitress "$candidate"; then
		PYTHON_BIN="$candidate"
		break
	fi
done

if [[ -z "$PYTHON_BIN" ]]; then
	echo "No Python with flask+waitress found for Control Center runner" >&2
	exit 1
fi

resolve_tailnet_ip() {
	"$PYTHON_BIN" - <<'PY'
import socket

try:
	short_host = socket.gethostname().split('.', 1)[0]
	ip = socket.gethostbyname(short_host)
	print(ip if ip.startswith('100.') else '')
except Exception:
	print('')
PY
}

cd "$PROJECT_DIR"
mkdir -p logs

WAITRESS_ARGS=(--listen=127.0.0.1:5001 --threads=8 control_center:app)
TAILNET_IP="$(resolve_tailnet_ip)"
if [[ -n "$TAILNET_IP" ]]; then
	WAITRESS_ARGS=(--listen="${TAILNET_IP}:5001" "${WAITRESS_ARGS[@]}")
fi

exec "$PYTHON_BIN" -m waitress "${WAITRESS_ARGS[@]}"
