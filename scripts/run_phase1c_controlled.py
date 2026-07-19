#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.research_phase1 as phase1


def main() -> int:
    tickers = ["CRWD", "NBIS", "OPRA", "VBNK", "ARTV", "SPCX"]
    collector = phase1.ResearchCollector()
    parser = phase1.ResearchParser()
    per_ticker = {}
    all_facts = []
    previous = {}
    current = {}

    for ticker in tickers:
        old_path = phase1.FACTS_DIR / f"{ticker}_phase1_facts.json"
        previous[ticker] = list((phase1._json_load(old_path, {}) or {}).get("facts") or [])

    for ticker in tickers:
        security_type = phase1.infer_security_type(ticker)
        print(f"START {ticker}", flush=True)
        collection = collector.collect_ticker(ticker, security_type)
        parsed = parser.parse_ticker(collection)
        current[ticker] = list(parsed.get("facts") or [])
        summary = phase1.build_phase1_report(ticker, security_type, collection, parsed)
        per_ticker[ticker] = {"security_type": security_type, "summary": summary}
        all_facts.extend(parsed.get("facts") or [])
        print(f"DONE {ticker} {summary['required_field_coverage_pct']}", flush=True)

    with phase1.FACT_STORE_PATH.open("w", encoding="utf-8") as handle:
        for fact in all_facts:
            handle.write(json.dumps(fact) + "\n")

    registry = phase1._write_official_source_registry(tickers)
    audit_rows = phase1._build_fact_status_audit(previous, current)
    phase1._json_dump(phase1.FACT_STATUS_AUDIT_PATH, {"generated_at": phase1._utc_now_iso(), "rows": audit_rows})

    run_summary = {
        "generated_at": phase1._utc_now_iso(),
        "tickers": tickers,
        "official_source_registry_path": str(phase1.OFFICIAL_SOURCE_REGISTRY_PATH),
        "fact_status_audit_path": str(phase1.FACT_STATUS_AUDIT_PATH),
        "per_ticker": {
            ticker: {
                "security_type": per_ticker[ticker]["security_type"],
                "summary": per_ticker[ticker]["summary"],
                "official_sources": registry.get(ticker, []),
            }
            for ticker in tickers
        },
    }
    phase1._json_dump(phase1.RUN_SUMMARY_PATH, run_summary)
    print(json.dumps(run_summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
