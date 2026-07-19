#!/usr/bin/env python3
"""Automate IBD CSV export through a persistent browser session.

One-time setup:
- Run this script manually with --headed and complete login if prompted.
- Keep session persisted in local browser profile directory.

Runtime behavior:
- Navigates to configured IBD export page.
- Clicks first matching export selector.
- Saves downloaded CSV into dedicated source folder for auto-import.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path


DEFAULT_SELECTORS = [
    "button:has-text('Export')",
    "button:has-text('CSV')",
    "a:has-text('Export')",
    "a:has-text('Download')",
    "[data-testid='export-button']",
    "[aria-label*='Export']",
]


def _visible_labels(locator, limit: int = 20) -> list[str]:
    labels: list[str] = []
    count = min(locator.count(), limit)
    for index in range(count):
        try:
            item = locator.nth(index)
            if not item.is_visible(timeout=250):
                continue
            text = " ".join((item.inner_text(timeout=500) or "").split())
            if text:
                labels.append(text[:120])
        except Exception:
            continue
    return labels


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automate IBD export download via Playwright.")
    parser.add_argument("--export-url", required=True, help="IBD page URL that has the export button.")
    parser.add_argument("--download-dir", default=str(Path.home() / "Downloads" / "IBD"), help="Destination folder for downloaded CSV exports.")
    parser.add_argument("--user-data-dir", default=str(Path.home() / "Library" / "Application Support" / "McLeod Alpha" / "ibd_browser_profile"), help="Persistent browser profile directory.")
    parser.add_argument("--selectors", default="||".join(DEFAULT_SELECTORS), help="Export button selectors separated by ||.")
    parser.add_argument("--headed", action="store_true", help="Run browser with visible window.")
    parser.add_argument("--timeout-ms", type=int, default=25000)
    parser.add_argument(
        "--max-wait-seconds",
        type=int,
        default=120,
        help="How long to keep retrying for export controls (useful for login/MFA in headed mode).",
    )
    parser.add_argument(
        "--retry-interval-ms",
        type=int,
        default=2500,
        help="Delay between export-control retries.",
    )
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        help="Browser channel for Playwright persistent context (default: chrome).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except Exception as exc:
        print("Playwright not installed. Install with: .venv/bin/python -m pip install playwright && .venv/bin/python -m playwright install chromium")
        print(f"Import error: {exc}")
        return 2

    download_dir = Path(args.download_dir).expanduser()
    user_data_dir = Path(args.user_data_dir).expanduser()
    download_dir.mkdir(parents=True, exist_ok=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    selectors = [s.strip() for s in args.selectors.split("||") if s.strip()]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel=args.browser_channel,
            headless=not args.headed,
            accept_downloads=True,
            downloads_path=str(download_dir),
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )
        try:
            context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = window.chrome || { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                """
            )
            page = context.new_page()
            page.goto(args.export_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            page.wait_for_timeout(1200)

            downloaded = None
            attempts = max(1, int((args.max_wait_seconds * 1000) / max(250, args.retry_interval_ms)))
            for attempt in range(attempts):
                for selector in selectors:
                    loc = page.locator(selector).first
                    try:
                        if not loc.is_visible(timeout=1200):
                            continue
                    except Exception:
                        continue

                    try:
                        with page.expect_download(timeout=9000) as download_info:
                            loc.click()
                        downloaded = download_info.value
                        logging.info("Triggered export via selector: %s", selector)
                        break
                    except PlaywrightTimeoutError:
                        continue
                    except Exception:
                        continue

                if downloaded is not None:
                    break

                # Give time for login redirects/MFA and dynamic page rendering.
                page.wait_for_timeout(args.retry_interval_ms)

            if downloaded is None:
                button_labels = _visible_labels(page.locator("button"))
                link_labels = _visible_labels(page.locator("a"))
                if button_labels:
                    logging.info("Visible buttons: %s", button_labels)
                if link_labels:
                    logging.info("Visible links: %s", link_labels)
                logging.error("Could not trigger IBD export. Check selectors or login state.")
                return 1

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = download_dir / f"ibd_export_{timestamp}.csv"
            downloaded.save_as(str(out_path))
            logging.info("Saved IBD export to %s", out_path)
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
