from __future__ import annotations

import json
from pathlib import Path

from tools.build_daytradespy_archive_manifest import build_manifest, write_manifest


def test_manifest_collects_all_pages_and_marks_transcripts_pending(tmp_path: Path) -> None:
    calls: list[int] = []

    def fetch_page(page: int) -> tuple[list[dict], int]:
        calls.append(page)
        return ([{"id": page, "date": f"2026-07-0{page}T09:30:00", "link": f"https://example.test/{page}", "title": {"rendered": f"Recording {page}"}}], 2)

    manifest = build_manifest(fetch_page=fetch_page)
    output = tmp_path / "archive_manifest.json"
    write_manifest(manifest, output)

    assert calls == [1, 2]
    assert manifest["recording_count"] == 2
    assert [item["post_id"] for item in manifest["recordings"]] == [2, 1]
    assert all(item["transcript_status"] == "pending" for item in manifest["recordings"])
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "daytradespy-archive-manifest.v1"