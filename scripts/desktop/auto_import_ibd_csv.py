#!/usr/bin/env python3
"""Near-automatic IBD CSV import.

Scans a source folder (default: ~/Downloads) for recent CSV exports,
normalizes known IBD header variants, and writes canonical output to
`data/ibd_rankings_manual.csv`.

This script does not access IBD credentials directly. It only ingests local CSV
exports produced by your logged-in browser session.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
DEST_CSV = DATA_DIR / "ibd_rankings_manual.csv"
STATE_FILE = DATA_DIR / "ibd_auto_import_state.json"
JSONL_LOG = LOG_DIR / "ibd_auto_import.jsonl"

CANONICAL_FIELDS = [
    "Symbol",
    "Composite",
    "EPS",
    "RS",
    "SMR",
    "Acc/Dis",
    "Industry Rank",
    "Date",
    "Notes",
]

HEADER_ALIASES = {
    "symbol": "Symbol",
    "ticker": "Symbol",
    "composite": "Composite",
    "composite rating": "Composite",
    "eps": "EPS",
    "eps rating": "EPS",
    "rs": "RS",
    "rs rating": "RS",
    "relative strength": "RS",
    "smr": "SMR",
    "smr rating": "SMR",
    "acc/dis": "Acc/Dis",
    "acc-dis": "Acc/Dis",
    "acc dist": "Acc/Dis",
    "accumulation/distribution": "Acc/Dis",
    "industry rank": "Industry Rank",
    "industry group rank": "Industry Rank",
    "date": "Date",
    "as of": "Date",
    "notes": "Notes",
}


def _setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ibd_auto_import")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(LOG_DIR / "ibd_auto_import.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def _append_jsonl(payload: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("logged_at", datetime.now().isoformat())
    with JSONL_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _normalize_header(name: str) -> str:
    return " ".join(name.strip().lower().replace("_", " ").split())


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_likely_ibd_csv(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
    except Exception:
        return False

    normalized = {_normalize_header(col) for col in header}
    needed = {"symbol", "composite"}
    return needed.issubset(normalized)


def _candidate_files(source_dir: Path, glob_pattern: str) -> list[Path]:
    if not source_dir.exists():
        return []
    files = [p for p in source_dir.glob(glob_pattern) if p.is_file()]
    files = [p for p in files if p.suffix.lower() == ".csv"]
    files = [p for p in files if _is_likely_ibd_csv(p)]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _canonicalize_row(raw_row: dict[str, str], default_date: str) -> dict[str, str] | None:
    mapped: dict[str, str] = {field: "" for field in CANONICAL_FIELDS}

    for key, value in raw_row.items():
        normalized = _normalize_header(key)
        target = HEADER_ALIASES.get(normalized)
        if not target:
            continue
        mapped[target] = (value or "").strip()

    symbol = mapped["Symbol"].upper().strip()
    if not symbol:
        return None

    mapped["Symbol"] = symbol
    mapped["Date"] = mapped["Date"] or default_date
    mapped["Notes"] = mapped["Notes"]
    return mapped


def _read_and_transform(source: Path) -> list[dict[str, str]]:
    default_date = datetime.now().strftime("%Y-%m-%d")
    transformed: list[dict[str, str]] = []

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = _canonicalize_row(raw, default_date)
            if row is None:
                continue
            transformed.append(row)

    # Keep last occurrence per symbol from source ordering.
    by_symbol: dict[str, dict[str, str]] = {}
    for row in transformed:
        by_symbol[row["Symbol"]] = row

    final_rows = sorted(by_symbol.values(), key=lambda r: r["Symbol"])
    return final_rows


def _write_canonical(rows: list[dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DEST_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-import IBD CSV export into canonical project file.")
    parser.add_argument("--source-dir", default=str(Path.home() / "Downloads" / "IBD"), help="Directory to scan for IBD CSV export files.")
    parser.add_argument("--glob", default="ibd*.csv", help="Glob to filter candidate files inside source-dir.")
    parser.add_argument("--force", action="store_true", help="Import even if source hash already imported.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write destination; only report what would happen.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logger = _setup_logger()

    source_dir = Path(args.source_dir).expanduser()
    candidates = _candidate_files(source_dir, args.glob)
    if not candidates:
        msg = f"No compatible IBD CSV found in {source_dir} using glob {args.glob}"
        logger.info(msg)
        _append_jsonl({"event": "skipped", "reason": "no_candidate", "source_dir": str(source_dir), "glob": args.glob})
        return 0

    source = candidates[0]
    source_hash = _sha256_file(source)
    state = _read_state()

    if not args.force and state.get("last_source_hash") == source_hash:
        logger.info("Latest IBD source already imported: %s", source)
        _append_jsonl({"event": "skipped", "reason": "already_imported", "source": str(source)})
        return 0

    rows = _read_and_transform(source)
    if not rows:
        logger.warning("Candidate file had no valid rows: %s", source)
        _append_jsonl({"event": "skipped", "reason": "no_valid_rows", "source": str(source)})
        return 0

    if args.dry_run:
        logger.info("Dry run: would import %s rows from %s", len(rows), source)
        _append_jsonl({"event": "dry_run", "rows": len(rows), "source": str(source)})
        return 0

    _write_canonical(rows)
    state_payload = {
        "last_source_path": str(source),
        "last_source_hash": source_hash,
        "last_source_mtime": datetime.fromtimestamp(source.stat().st_mtime).isoformat(),
        "last_imported_at": datetime.now().isoformat(),
        "last_row_count": len(rows),
        "destination": str(DEST_CSV),
    }
    _write_state(state_payload)

    logger.info("Imported %s rows from %s -> %s", len(rows), source, DEST_CSV)
    _append_jsonl({"event": "imported", "rows": len(rows), "source": str(source), "destination": str(DEST_CSV)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
