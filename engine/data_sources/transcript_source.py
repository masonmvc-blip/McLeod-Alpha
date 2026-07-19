#!/usr/bin/env python3
"""Earnings-call material source from official public filings.

This source only uses reliable public endpoints and does not bypass access
controls or paywalls. It prefers SEC-filed and investor-relations style
materials available through SEC submissions archives.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from engine.data_sources.sec_source import SECDataSource


WORKSPACE = Path(__file__).parent.parent.parent
DATA_DIR = WORKSPACE / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_FILE = CACHE_DIR / "transcript_source_cache.json"

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


def _clean_text(raw: str) -> str:
    text = raw
    text = re.sub(r"<script[\\s\\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()


def _first_sentence_with_keywords(text: str, keywords: List[str], limit: int = 220) -> Optional[str]:
    if not text:
        return None
    parts = re.split(r"(?<=[.!?])\\s+", text)
    lower_keywords = [k.lower() for k in keywords]
    for sentence in parts:
        s = sentence.strip()
        if len(s) < 30:
            continue
        lower = s.lower()
        if any(k in lower for k in lower_keywords):
            return s[:limit]
    return None


class TranscriptDataSource:
    """Fetch official earnings-call materials with local cache and retries."""

    def __init__(self):
        self.name = "SEC Official Earnings Materials"
        self.cache_ttl_hours = 48
        self.max_retries = 2
        self.retry_backoff_seconds = 1.0
        self.max_documents = 6
        self.lookback_days = 550
        self.confidence_base = 76
        self.sec_source = SECDataSource()

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "McLeod Earnings Intelligence 1.0 (research@mcleodcapital.com)"})
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if not CACHE_FILE.exists():
            return {}
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                payload = json.load(f)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_cache(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    def _cache_is_fresh(self, ts: str) -> bool:
        try:
            dt = datetime.fromisoformat(ts)
            age_hours = (datetime.now() - dt).total_seconds() / 3600.0
            return age_hours <= float(self.cache_ttl_hours)
        except Exception:
            return False

    def _request_json(self, url: str) -> Optional[Dict[str, Any]]:
        for attempt in range(1, self.max_retries + 1):
            try:
                res = self.session.get(url, timeout=12)
                if res.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {res.status_code}")
                res.raise_for_status()
                payload = res.json()
                return payload if isinstance(payload, dict) else None
            except Exception:
                if attempt >= self.max_retries:
                    return None
                time.sleep(self.retry_backoff_seconds * attempt)
        return None

    def _request_text(self, url: str) -> Optional[str]:
        for attempt in range(1, self.max_retries + 1):
            try:
                res = self.session.get(url, timeout=12)
                if res.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {res.status_code}")
                res.raise_for_status()
                return res.text
            except Exception:
                if attempt >= self.max_retries:
                    return None
                time.sleep(self.retry_backoff_seconds * attempt)
        return None

    def _request_filing_index(self, cik_no_zeros: str, accession_nodash: str) -> List[str]:
        url = f"{SEC_ARCHIVES_BASE}/{cik_no_zeros}/{accession_nodash}/index.json"
        payload = self._request_json(url)
        if not payload:
            return []

        directory = payload.get("directory") if isinstance(payload, dict) else None
        items = directory.get("item", []) if isinstance(directory, dict) else []

        names: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if name:
                names.append(name)
        return names

    @staticmethod
    def _iter_recent_filings(submissions: Dict[str, Any]) -> List[Dict[str, str]]:
        recent = (submissions.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        filing_dates = recent.get("filingDate") or []
        accession = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        report_dates = recent.get("reportDate") or []

        out: List[Dict[str, str]] = []
        for i in range(min(len(forms), len(filing_dates), len(accession), len(primary_docs))):
            form = str(forms[i] or "").upper()
            if form not in {"8-K", "10-Q", "10-K"}:
                continue
            filed = str(filing_dates[i] or "")
            try:
                filed_dt = datetime.strptime(filed, "%Y-%m-%d")
            except Exception:
                continue
            if filed_dt < (datetime.now() - timedelta(days=550)):
                continue

            out.append(
                {
                    "form": form,
                    "filing_date": filed,
                    "report_date": str(report_dates[i] or ""),
                    "accession_number": str(accession[i] or ""),
                    "primary_document": str(primary_docs[i] or ""),
                }
            )
        return out

    @staticmethod
    def _is_earnings_related(filename: str, text: str) -> bool:
        name = (filename or "").lower()
        t = (text or "").lower()
        filename_hit = any(k in name for k in ["earn", "result", "release", "press", "ex99", "presentation", "remarks"])
        text_hit = any(k in t for k in ["earnings", "conference call", "prepared remarks", "guidance", "fiscal quarter"]) 
        return filename_hit or text_hit

    @staticmethod
    def _candidate_document_names(primary_doc: str, filing_index_names: List[str]) -> List[str]:
        ordered: List[str] = []
        seen = set()

        def add(name: str) -> None:
            clean = str(name or "").strip()
            if not clean or clean in seen:
                return
            seen.add(clean)
            ordered.append(clean)

        add(primary_doc)

        preferred_patterns = [
            "ex99",
            "99.1",
            "99_1",
            "earn",
            "result",
            "release",
            "press",
            "presentation",
            "remark",
            "call",
        ]
        allowed_suffixes = (".htm", ".html", ".txt")

        ranked: List[tuple[int, str]] = []
        for name in filing_index_names:
            low = name.lower()
            if low.endswith("/") or not low.endswith(allowed_suffixes):
                continue
            score = 0
            for idx, pattern in enumerate(preferred_patterns):
                if pattern in low:
                    score += 20 - idx
            if score <= 0:
                continue
            ranked.append((score, name))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        for _, name in ranked[:8]:
            add(name)
        return ordered

    def fetch_symbol(self, symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
        symbol = str(symbol or "").upper().strip()
        now_iso = datetime.now().isoformat()

        if not symbol:
            return {
                "symbol": symbol,
                "timestamp": now_iso,
                "source": self.name,
                "stale": True,
                "confidence": 0,
                "source_urls": [],
                "data": {},
            }

        cached = self.cache.get(symbol)
        if cached and not force_refresh and self._cache_is_fresh(str(cached.get("timestamp", ""))):
            return {
                "symbol": symbol,
                "timestamp": str(cached.get("timestamp", now_iso)),
                "source": self.name,
                "stale": False,
                "confidence": int(cached.get("confidence", self.confidence_base)),
                "source_urls": list(cached.get("source_urls", [])),
                "data": dict(cached.get("data", {})),
            }

        cik = self.sec_source.get_cik_for_ticker(symbol)
        if not cik:
            return {
                "symbol": symbol,
                "timestamp": now_iso,
                "source": self.name,
                "stale": True,
                "confidence": 0,
                "source_urls": [],
                "data": {},
            }

        submissions = self._request_json(SUBMISSIONS_URL.format(cik=cik))
        if submissions is None:
            if cached:
                return {
                    "symbol": symbol,
                    "timestamp": str(cached.get("timestamp", now_iso)),
                    "source": self.name,
                    "stale": True,
                    "confidence": max(25, int(cached.get("confidence", self.confidence_base)) - 20),
                    "source_urls": list(cached.get("source_urls", [])),
                    "data": dict(cached.get("data", {})),
                }
            return {
                "symbol": symbol,
                "timestamp": now_iso,
                "source": self.name,
                "stale": True,
                "confidence": 0,
                "source_urls": [],
                "data": {},
            }

        filings = self._iter_recent_filings(submissions)[: self.max_documents]
        cik_no_zeros = str(int(cik))

        docs: List[Dict[str, Any]] = []
        source_urls: List[str] = []
        corpus_parts: List[str] = []

        for filing in filings:
            accession = filing.get("accession_number", "")
            primary_doc = filing.get("primary_document", "")
            if not accession or not primary_doc:
                continue

            accession_nodash = accession.replace("-", "")
            filing_index_names = self._request_filing_index(cik_no_zeros, accession_nodash)
            for document_name in self._candidate_document_names(primary_doc, filing_index_names):
                doc_url = f"{SEC_ARCHIVES_BASE}/{cik_no_zeros}/{accession_nodash}/{document_name}"
                raw_text = self._request_text(doc_url)
                if not raw_text:
                    continue

                cleaned = _clean_text(raw_text)
                if not self._is_earnings_related(document_name, cleaned):
                    continue

                excerpt = _first_sentence_with_keywords(
                    cleaned,
                    [
                        "earnings",
                        "conference call",
                        "prepared remarks",
                        "guidance",
                        "demand",
                        "margin",
                        "pricing",
                    ],
                    limit=220,
                )

                docs.append(
                    {
                        "filing_date": filing.get("filing_date", ""),
                        "report_date": filing.get("report_date", ""),
                        "form": filing.get("form", ""),
                        "accession_number": accession,
                        "url": doc_url,
                        "excerpt": excerpt or "",
                    }
                )
                source_urls.append(doc_url)
                corpus_parts.append(cleaned[:50000])

        combined_text = "\n\n".join(corpus_parts)[:180000]
        data = {
            "materials": docs,
            "combined_text": combined_text,
            "material_count": len(docs),
            "transcript_available": len(docs) > 0,
        }

        confidence = 0
        if docs:
            confidence = min(90, self.confidence_base + min(12, len(docs) * 2))

        self.cache[symbol] = {
            "timestamp": now_iso,
            "confidence": confidence,
            "source_urls": source_urls,
            "data": data,
        }
        self._save_cache()

        return {
            "symbol": symbol,
            "timestamp": now_iso,
            "source": self.name,
            "stale": False,
            "confidence": confidence,
            "source_urls": source_urls,
            "data": data,
        }
