#!/usr/bin/env python3
"""Official SEC Form 4 insider transaction source.

Uses only SEC EDGAR public filings. Parses raw ownership XML when available and
never fabricates missing values.
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from engine.data_sources.sec_source import SECDataSource


WORKSPACE = Path(__file__).parent.parent.parent
DATA_DIR = WORKSPACE / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_FILE = CACHE_DIR / "insider_source_cache.json"

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

FORM4_TYPES = {"4", "4/A"}


def _text(node: Optional[ET.Element], path: str, default: str = "") -> str:
    if node is None:
        return default
    found = node.find(path)
    if found is None or found.text is None:
        return default
    return str(found.text).strip()


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, "", "NA", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_text(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


class InsiderDataSource:
    """Fetch and parse official SEC Form 4 filings by symbol."""

    def __init__(self):
        self.name = "SEC Form 4 Insider Transactions"
        self.cache_ttl_hours = 24
        self.max_retries = 2
        self.retry_backoff_seconds = 1.0
        self.lookback_days = 400
        self.max_filings_per_symbol = 4
        self.confidence_base = 88
        self.sec_source = SECDataSource()

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "McLeod Insider Intelligence 1.0 (research@mcleodcapital.com)"})
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
            age = (datetime.now() - dt).total_seconds() / 3600.0
            return age <= float(self.cache_ttl_hours)
        except Exception:
            return False

    def _request_json(self, url: str) -> Optional[Dict[str, Any]]:
        for attempt in range(1, self.max_retries + 1):
            try:
                res = self.session.get(url, timeout=15)
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
                res = self.session.get(url, timeout=15)
                if res.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {res.status_code}")
                res.raise_for_status()
                return res.text
            except Exception:
                if attempt >= self.max_retries:
                    return None
                time.sleep(self.retry_backoff_seconds * attempt)
        return None

    def _recent_form4_filings(self, submissions: Dict[str, Any]) -> List[Dict[str, str]]:
        recent = (submissions.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        filing_dates = recent.get("filingDate") or []
        accession = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []

        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        out: List[Dict[str, str]] = []
        n = min(len(forms), len(filing_dates), len(accession), len(primary_docs))
        for i in range(n):
            form = str(forms[i] or "").upper()
            if form not in FORM4_TYPES:
                continue
            filed = str(filing_dates[i] or "")
            try:
                filed_dt = datetime.strptime(filed, "%Y-%m-%d")
            except Exception:
                continue
            if filed_dt < cutoff:
                continue
            out.append(
                {
                    "form": form,
                    "filing_date": filed,
                    "accession_number": str(accession[i] or ""),
                    "primary_document": str(primary_docs[i] or ""),
                }
            )
        return out[: self.max_filings_per_symbol]

    def _filing_xml_url(self, cik: str, accession_number: str, primary_document: str) -> Optional[str]:
        accession_nodash = accession_number.replace("-", "")
        primary_basename = primary_document.split("/")[-1].strip()
        if primary_basename.lower().endswith(".xml"):
            return f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_nodash}/{primary_basename}"

        index_url = f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_nodash}/index.json"
        index_payload = self._request_json(index_url)
        if not index_payload:
            return None

        items = (index_payload.get("directory") or {}).get("item") or []
        xml_names = [str(item.get("name", "")) for item in items if str(item.get("name", "")).lower().endswith(".xml")]
        if not xml_names:
            return None

        preferred = None
        base_name = primary_document.split("/")[-1]
        if base_name.lower().endswith(".xml") and base_name in xml_names:
            preferred = base_name
        if preferred is None:
            for name in xml_names:
                if "ownership" in name.lower() or "form4" in name.lower() or "4" in name.lower():
                    preferred = name
                    break
        if preferred is None:
            preferred = xml_names[-1]

        return f"{SEC_ARCHIVES_BASE}/{int(cik)}/{accession_nodash}/{preferred}"

    @staticmethod
    def _classify_transaction(code: str, acquired_disposed: str, is_10b5_1: bool) -> str:
        code_u = str(code or "").upper().strip()
        ad = str(acquired_disposed or "").upper().strip()
        if code_u == "P":
            return "open-market purchase"
        if code_u == "S":
            return "automatic 10b5-1 sale" if is_10b5_1 else "open-market sale"
        if code_u in {"M", "C"}:
            return "option exercise"
        if code_u in {"A"}:
            return "restricted stock grant"
        if code_u in {"F"}:
            return "tax withholding"
        if code_u in {"G"}:
            return "gift"
        if ad == "D" and code_u in {"D"}:
            return "other non-discretionary transaction"
        return "other non-discretionary transaction"

    @staticmethod
    def _role_from_relationship(rel: ET.Element) -> Dict[str, str]:
        title = _text(rel, "officerTitle", "")
        is_director = _bool_text(_text(rel, "isDirector", "0"))
        is_officer = _bool_text(_text(rel, "isOfficer", "0"))
        is_other = _bool_text(_text(rel, "isOther", "0"))
        other_text = _text(rel, "otherText", "")

        role = title or other_text or "Director" if is_director else "Insider"
        if title:
            role = title
        elif is_director:
            role = "Director"
        elif is_officer:
            role = "Officer"
        elif is_other:
            role = other_text or "Other"

        return {
            "insider_title": role.strip() or "Insider",
            "is_director": "1" if is_director else "0",
            "is_officer": "1" if is_officer else "0",
            "is_other": "1" if is_other else "0",
            "other_text": other_text,
        }

    def _parse_filing(self, symbol: str, filing: Dict[str, str], xml_text: str, source_url: str) -> List[Dict[str, Any]]:
        root = ET.fromstring(xml_text)
        filing_date = filing.get("filing_date", "")
        transaction_date_default = _text(root, "periodOfReport", filing_date)
        is_10b5_one = _bool_text(_text(root, "aff10b5One", "0"))

        footnotes = {}
        footnotes_root = root.find("footnotes")
        if footnotes_root is not None:
            for fn in footnotes_root.findall("footnote"):
                footnotes[str(fn.attrib.get("id", ""))] = (fn.text or "").strip()

        remarks_text = _text(root, "remarks", "")
        if not is_10b5_one:
            lower_combined = " ".join(list(footnotes.values()) + [remarks_text]).lower()
            if "10b5-1" in lower_combined or "10b5 1" in lower_combined:
                is_10b5_one = True

        owner = root.find("reportingOwner")
        owner_name = _text(owner, "reportingOwnerId/rptOwnerName", "")
        rel = owner.find("reportingOwnerRelationship") if owner is not None else None
        role_meta = self._role_from_relationship(rel) if rel is not None else {
            "insider_title": "Insider",
            "is_director": "0",
            "is_officer": "0",
            "is_other": "0",
            "other_text": "",
        }

        transactions: List[Dict[str, Any]] = []

        def parse_transactions(table_name: str, node_name: str, derivative_flag: str) -> None:
            table = root.find(table_name)
            if table is None:
                return
            for tx in table.findall(node_name):
                code = _text(tx, "transactionCoding/transactionCode", "")
                shares = _to_float(_text(tx, "transactionAmounts/transactionShares/value", ""), None)
                price = _to_float(_text(tx, "transactionAmounts/transactionPricePerShare/value", ""), None)
                ad_code = _text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value", "")
                ownership_after = _to_float(_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value", ""), None)
                direct_indirect = _text(tx, "ownershipNature/directOrIndirectOwnership/value", "")
                transaction_date = _text(tx, "transactionDate/value", transaction_date_default)
                sec_title = _text(tx, "securityTitle/value", "")

                ownership_before = None
                if shares is not None and ownership_after is not None:
                    if ad_code == "A":
                        ownership_before = ownership_after - shares
                    elif ad_code == "D":
                        ownership_before = ownership_after + shares

                pct_increase = None
                if shares is not None and ownership_before not in (None, 0):
                    pct_increase = (shares / ownership_before) * 100.0

                tx_type = self._classify_transaction(code, ad_code, is_10b5_one)
                total_value = None
                if shares is not None and price is not None:
                    total_value = shares * price

                transactions.append(
                    {
                        "ticker": symbol,
                        "insider_name": owner_name,
                        "insider_title": role_meta["insider_title"],
                        "transaction_date": transaction_date,
                        "filing_date": filing_date,
                        "transaction_type": tx_type,
                        "transaction_code": code,
                        "shares": shares,
                        "price": price,
                        "total_dollar_value": total_value,
                        "direct_or_indirect_ownership": direct_indirect,
                        "ownership_before": ownership_before,
                        "ownership_after": ownership_after,
                        "pct_increase_ownership": pct_increase,
                        "ten_b_five_one_indicator": "1" if is_10b5_one else "0",
                        "sec_accession_number": filing.get("accession_number", ""),
                        "source_url": source_url,
                        "security_title": sec_title,
                        "derivative_flag": derivative_flag,
                        "filing_form": filing.get("form", "4"),
                    }
                )

        parse_transactions("nonDerivativeTable", "nonDerivativeTransaction", "0")
        parse_transactions("derivativeTable", "derivativeTransaction", "1")
        return transactions

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
                "data": {"transactions": []},
            }

        cached = self.cache.get(symbol)
        if cached and not force_refresh and self._cache_is_fresh(str(cached.get("timestamp", ""))):
            return {
                "symbol": symbol,
                "timestamp": str(cached.get("timestamp", now_iso)),
                "source": self.name,
                "stale": False,
                "confidence": int(cached.get("confidence", self.confidence_base)),
                "data": cached.get("data", {"transactions": []}),
            }

        cik = self.sec_source.get_cik_for_ticker(symbol)
        if not cik:
            return {
                "symbol": symbol,
                "timestamp": now_iso,
                "source": self.name,
                "stale": True,
                "confidence": 0,
                "data": {"transactions": []},
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
                    "data": cached.get("data", {"transactions": []}),
                }
            return {
                "symbol": symbol,
                "timestamp": now_iso,
                "source": self.name,
                "stale": True,
                "confidence": 0,
                "data": {"transactions": []},
            }

        filings = self._recent_form4_filings(submissions)
        transactions: List[Dict[str, Any]] = []
        for filing in filings:
            xml_url = self._filing_xml_url(cik, filing.get("accession_number", ""), filing.get("primary_document", ""))
            if not xml_url:
                continue
            xml_text = self._request_text(xml_url)
            if not xml_text:
                continue
            try:
                parsed = self._parse_filing(symbol, filing, xml_text, xml_url)
                transactions.extend(parsed)
            except Exception:
                continue

        confidence = self.confidence_base if transactions else 40
        payload = {
            "transactions": transactions,
            "forms_seen": [f.get("accession_number", "") for f in filings],
            "cik": cik,
        }
        self.cache[symbol] = {
            "timestamp": now_iso,
            "confidence": confidence,
            "data": payload,
        }
        self._save_cache()

        return {
            "symbol": symbol,
            "timestamp": now_iso,
            "source": self.name,
            "stale": False,
            "confidence": confidence,
            "data": payload,
        }
