#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"

if [[ "${1:-}" == "canonical-autodeploy" ]]; then
	shift
	exec /bin/zsh "$SCRIPT_DIR/install_canonical_autodeploy_launchagent.sh" "$@"
fi

exec /bin/zsh "$SCRIPT_DIR/install_morning_cio_email_launchagent.sh" "$@"