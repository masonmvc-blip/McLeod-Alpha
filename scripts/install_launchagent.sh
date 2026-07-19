#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
exec /bin/zsh "$SCRIPT_DIR/install_morning_cio_email_launchagent.sh" "$@"