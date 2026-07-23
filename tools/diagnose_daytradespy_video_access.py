#!/usr/bin/env python3
"""Inspect public DayTradeSPY post embed metadata without accessing protected media."""

from __future__ import annotations

import argparse
import json
import re
import ssl
from typing import Any
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:  # pragma: no cover - optional runtime dependency
    certifi = None


def inspect_post(post_id: int) -> dict[str, Any]:
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
    request = Request(
        f"https://daytradespy.com/wp-json/wp/v2/posts/{post_id}?_fields=id,link,content",
        headers={"User-Agent": "McLeodAlphaResearch/1.0"},
    )
    with urlopen(request, context=context, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = str((payload.get("content") or {}).get("rendered") or "")
    video_ids = sorted(set(re.findall(r"(?:vimeo\.com/(?:video/)?)(\d+)", content)))
    return {
        "post_id": int(payload["id"]),
        "source_url": str(payload.get("link") or ""),
        "public_embed_indicators": {"vimeo_video_ids": video_ids, "contains_vimeo": "vimeo" in content.lower()},
        "access_rule": "A protected player must be viewed with source-authorized access; this diagnostic does not request media or captions.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("post_id", type=int)
    args = parser.parse_args()
    print(json.dumps(inspect_post(args.post_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())