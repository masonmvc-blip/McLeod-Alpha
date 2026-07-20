# Morning CIO Reporting

The canonical implementation lives in this GitHub checkout. Dropbox paths are
legacy and must not be used by code, wrappers, logs, or LaunchAgents.

## CLI

Generate artifacts without sending email:

```bash
.venv-1/bin/python tools/send_cio_report.py --date YYYY-MM-DD --dry-run
```

Generate and deliver the report:

```bash
.venv-1/bin/python tools/send_cio_report.py --date YYYY-MM-DD --send
```

Successful delivery is idempotent by report date. Use `--force` only when an
intentional repeat delivery is required; it also bypasses the market-session
gate for manual testing.

## Outputs

Latest artifacts are written under `data/reports/morning_cio_email/`. Each run
also writes HTML, Markdown, and JSON under
`data/reports/morning_cio_email/archive/YYYY-MM-DD/`. Delivery metadata is
appended to `delivery_registry.jsonl`; credentials and message bodies are never
stored there.

## Credentials

Copy `.env.example` to the ignored `.env` file and configure a Gmail app
password. The LaunchAgent contains no credentials. SMTP-only mode is the
production default; Mail.app fallback must be explicitly enabled by setting
`MORNING_CIO_REQUIRE_SMTP_ONLY=false`.

## Scheduling

Install the user LaunchAgent from this checkout:

```bash
/bin/zsh scripts/install_morning_cio_email_launchagent.sh
```

It runs at 7:00 AM America/Chicago and uses the XNYS market calendar to skip
non-session days. Installation does not immediately send a report unless
`--run-now` is explicitly supplied.
