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
	echo "No Python with flask+waitress found for Cockpit runner" >&2
	exit 1
fi

cd "$PROJECT_DIR"
mkdir -p logs

WAITRESS_ARGS=(--listen=127.0.0.1:5001 --threads=8 cockpit:app)

exec "$PYTHON_BIN" -m waitress "${WAITRESS_ARGS[@]}"
