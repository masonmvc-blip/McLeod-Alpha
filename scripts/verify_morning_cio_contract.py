#!/usr/bin/env python3
"""Verify canonical Morning CIO execution contract.

Fails if active scheduling/execution scripts reference legacy report paths.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FILES = [
    ROOT / "scripts" / "run_morning_cio_email.sh",
    ROOT / "scripts" / "install_morning_cio_email_launchagent.sh",
]
FORBIDDEN = ["reports/morning_cio_report.py"]
REQUIRED = ["-m cio_email.morning_report --send"]


def main() -> int:
    failures = []
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in text:
                failures.append(f"forbidden_token:{token}:{path}")
        for token in REQUIRED:
            if token not in text:
                failures.append(f"required_token_missing:{token}:{path}")

    if failures:
        print("Morning CIO contract verification failed:")
        for item in failures:
            print(f"- {item}")
        return 2

    print("Morning CIO contract verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
