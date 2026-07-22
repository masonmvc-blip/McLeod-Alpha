#!/usr/bin/env python3
"""Build a resumable manifest for Day Trade SPY's public video archive."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://daytradespy.com/wp-json/wp/v2/posts"
ARCHIVE_CATEGORY_ID = 4
FIELDS = "id,date,link,title"


def _fetch_page(page: int, *, opener=urlopen) -> tuple[list[dict[str, Any]], int]:
    query = urlencode(
        {
            "categories": ARCHIVE_CATEGORY_ID,
            "per_page": 100,
            "page": page,
            "orderby": "date",
            "order": "desc",
            "_fields": FIELDS,
        }
    )
    request = Request(f"{API_URL}?{query}", headers={"User-Agent": "McLeodAlphaResearch/1.0"})
    with opener(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
        total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
    if not isinstance(payload, list):
        raise ValueError("Day Trade SPY archive response is not a post list")
    return payload, total_pages


def build_manifest(*, fetch_page=_fetch_page) -> dict[str, Any]:
    posts: list[dict[str, Any]] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        batch, total_pages = fetch_page(page)
        posts.extend(batch)
        page += 1

    recordings = [
        {
            "post_id": int(post["id"]),
            "recording_date": str(post["date"]),
            "title": str((post.get("title") or {}).get("rendered") or ""),
            "source_url": str(post["link"]),
            "transcript_status": "pending",
            "transcript_path": "",
            "analysis_status": "pending",
        }
        for post in posts
    ]
    recordings.sort(key=lambda item: (item["recording_date"], item["post_id"]), reverse=True)
    return {
        "schema_version": "daytradespy-archive-manifest.v1",
        "source": "Day Trade SPY public WordPress archive category 4",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "recording_count": len(recordings),
        "recordings": recordings,
    }


def write_manifest(manifest: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/daytradespy/archive_manifest.json"),
        help="Generated manifest path.",
    )
    args = parser.parse_args(argv)
    manifest = build_manifest()
    write_manifest(manifest, args.output)
    print(f"{args.output}: {manifest['recording_count']} recordings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())