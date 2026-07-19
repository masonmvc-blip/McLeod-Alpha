#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
PY="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  PY="/usr/bin/python3"
fi

status_ok=1

echo "=== Desktop Performance Preflight ==="
echo "Root: $ROOT_DIR"

echo "\n[1] Sleep/App Nap Guard"
if [[ -f "$ROOT_DIR/.power_guard.pid" ]]; then
  pid=$(cat "$ROOT_DIR/.power_guard.pid" 2>/dev/null || true)
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "PASS: power guard running (PID $pid)"
  else
    echo "WARN: power guard pid file exists but process is not running"
    status_ok=0
  fi
else
  echo "WARN: power guard not running (start scripts/desktop/start_power_guard.sh)"
  status_ok=0
fi

echo "\n[2] Primary Network"
iface=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' | head -n1)
if [[ -z "${iface:-}" ]]; then
  echo "WARN: unable to detect primary interface"
  status_ok=0
else
  hw=$(networksetup -listallhardwareports 2>/dev/null | awk -v d="$iface" 'BEGIN{p=""} /Hardware Port:/{p=substr($0,16)} /Device:/{if(substr($0,9)==d){print p; exit}}')
  echo "Primary interface: $iface (${hw:-unknown})"
  hw_lower=$(echo "${hw:-}" | tr '[:upper:]' '[:lower:]')
  if [[ "$hw_lower" == *"ethernet"* || "$hw_lower" == *"lan"* ]]; then
    echo "PASS: wired network detected"
  else
    echo "WARN: primary network is not Ethernet"
    status_ok=0
  fi
fi

echo "\n[3] Python Runtime"
"$ROOT_DIR/scripts/desktop/verify_python_runtime.sh" || status_ok=0

echo "\n[4] Token Conflict Check"
conflicts=$(find "$ROOT_DIR" -maxdepth 1 -type f -name 'token*conflicted copy*.json' | wc -l | tr -d ' ')
if [[ "$conflicts" == "0" ]]; then
  echo "PASS: no conflicted token files"
else
  echo "WARN: conflicted token files found: $conflicts"
  status_ok=0
fi

echo "\n[5] Disk & I/O"
free_kb=$(df -k "$ROOT_DIR" | awk 'NR==2{print $4}')
free_gb=$((free_kb / 1024 / 1024))
echo "Free space: ${free_gb}GB"
if (( free_gb < 10 )); then
  echo "WARN: free disk below 10GB"
  status_ok=0
else
  echo "PASS: free disk healthy"
fi

echo "\n[6] LaunchAgent Checks"
for label in \
  com.mcleod.alpha.cio-report \
  com.mcleod.alpha.spcx-open-assist \
  com.mcleod.alpha.preopen-health-bundle \
  com.mcleod.alpha.runtime-log-rotation \
  com.mcleod.alpha.power-guard-start \
  com.mcleod.alpha.power-guard-stop
do
  if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    echo "PASS: $label installed"
  else
    echo "WARN: $label not installed"
    status_ok=0
  fi
done

if [[ "$status_ok" == "1" ]]; then
  echo "\nPreflight: PASS"
  exit 0
fi

echo "\nPreflight: WARN"
exit 2
