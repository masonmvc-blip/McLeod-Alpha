# Cockpit Canonicalization Migration

Date: 2026-07-20

## Supported Interface

The only supported public management interface is:

`https://cockpit.mcleodalpha.com`

The Cloudflare-protected Cockpit is the sole public control plane. The private loopback origin is used only by the local Flask or Waitress process, Cloudflare Tunnel, watchdogs, and local restart or diagnostic tooling. It is not a documented, emailed, alerted, or user-facing link.

## Source of Truth

`config/cockpit.env` defines the one canonical value:

```sh
COCKPIT_PUBLIC_URL=https://cockpit.mcleodalpha.com
```

Python consumers load this file with `dotenv`; shell consumers source it. Public health checks, daily validation, deployment scripts, and launch-agent installation use this value instead of embedding a hostname.

## Changed Files

- `config/cockpit.env`: added the shared public URL constant.
- `cockpit.py`: loads the shared constant; removes legacy host redirect behavior; publishes the canonical public URL in status and go-live responses.
- `ops/run_cockpit_waitress.sh`: listens only on the private loopback origin; removes legacy listener resolution.
- `ops/check_live_runtime_health.py`: reads the canonical public status endpoint.
- `scripts/daily_execution_validation.py`: reads the canonical public endpoint.
- `scripts/maintenance/go_live.sh`
- `scripts/maintenance/laptop_ship_and_deploy.sh`
- `scripts/maintenance/lock_canonical_runtime.sh`
- `scripts/maintenance/post_deploy_smoke_check.sh`
- `scripts/maintenance/promote_canonical_runtime.sh`
- `scripts/maintenance/sync_and_restart_from_start_button.sh`
- `scripts/install_nightly_sync_restart_launchagent.sh`: use the shared public URL configuration.
- `scripts/maintenance/start_cockpit_guarded.sh`: removes obsolete redirect enforcement.
- `scripts/recover_canonical_cockpit.sh`: removes obsolete redirect setup and legacy recovery guidance.
- `COCKPIT_README.md`, `STARTUP_CHECKLIST.md`, and `docs/ARCHITECTURE_V1.0_RELEASE.md`: replace legacy public access guidance with the canonical Cloudflare Cockpit.

## Retired Behavior

- Legacy private-network Cockpit endpoints are no longer configured or documented as public management interfaces.
- The Cockpit root route no longer applies host-based HTTP redirects.
- The `MCLEOD_CANONICAL_COCKPIT_URL` and `MCLEOD_REDIRECT_NONCANONICAL_COCKPIT` control-plane settings are retired.
- The Waitress runner no longer exposes a legacy public listener.

## Verification Contract

A canonicalization validation must confirm all of the following:

1. No tracked active source, script, test, or documentation contains a legacy private-network Cockpit reference or retired redirect setting.
2. Every public Cockpit link resolves through `COCKPIT_PUBLIC_URL` and targets `https://cockpit.mcleodalpha.com`.
3. The private listener appears only in origin, tunnel, watchdog, or local control paths.
4. Cockpit serves its private origin without a redirect, allowing the Cloudflare Tunnel to proxy it.

## Validation Results

- Local root response: `200 OK`, with no redirect.
- Status response: publishes `cockpit_public_url` as `https://cockpit.mcleodalpha.com` and omits the retired redirect status field.
- Canonical public domain: reachable and protected by Cloudflare Access before authentication.
- Static checks: Python compilation, shell syntax, and diff whitespace checks passed.
- Focused regression suite: `10 passed`.
