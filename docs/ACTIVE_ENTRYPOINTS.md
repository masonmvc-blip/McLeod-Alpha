# Active Entrypoints

Use these scripts as the canonical operational flow.

## Canonical Runtime Flow

- Start: ops/stack_start.sh
- Status: ops/stack_status.sh
- Stop: ops/stack_stop.sh
- Control Center (direct): ops/run_control_center_waitress.sh
- Watchdog: ops/runtime_watchdog.sh

## Policy

- New runbooks should call the scripts above instead of ad-hoc commands.
- Legacy scripts in archive are historical references, not active runtime paths.
- If a legacy runner is still needed, convert it to a thin wrapper that calls these scripts.
