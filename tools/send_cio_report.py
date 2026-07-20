#!/usr/bin/env python3
"""Canonical CLI for generating and delivering the Morning CIO report."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cio_email.morning_report import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
