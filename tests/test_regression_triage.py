from __future__ import annotations

import json
from pathlib import Path

from tools.triage_regression_failures import main


def test_triage_inventory_is_complete_and_deterministic(tmp_path: Path) -> None:
    report = tmp_path / "pytest.txt"
    report.write_text(
        "\n".join((
            "FAILED tests/test_stop.py::test_stop - TypeError: can't subtract offset-naive and offset-aware datetimes",
            "FAILED tests/test_monitor.py::test_helper - AttributeError: module 'phase3_monitor' has no attribute 'helper'",
            "FAILED tests/test_data.py::test_history - FileNotFoundError: CSV file not found: fixture.csv",
        )) + "\n",
        encoding="utf-8",
    )
    first_json, first_markdown = tmp_path / "first.json", tmp_path / "first.md"
    second_json, second_markdown = tmp_path / "second.json", tmp_path / "second.md"
    assert main(["--report", str(report), "--json-output", str(first_json), "--markdown-output", str(first_markdown)]) == 0
    assert main(["--report", str(report), "--json-output", str(second_json), "--markdown-output", str(second_markdown)]) == 0
    payload = json.loads(first_json.read_text(encoding="utf-8"))
    assert payload["failure_count"] == 3
    assert payload["category_counts"] == {"LEGACY_API_MISMATCH": 1, "MISSING_FIXTURE": 1, "TIMEZONE_BUG": 1}
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_markdown.read_bytes() == second_markdown.read_bytes()