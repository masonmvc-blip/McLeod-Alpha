#!/usr/bin/env python3
"""Phase 1 Research Pipeline: collector -> parser -> structured fact store.

Phase 1B extends source adapters, taxonomy coverage, and diagnostics while
remaining strictly pre-valuation. No expected-return, EIPV, approvals, or
recommendations are produced in this module.
"""

from __future__ import annotations

import hashlib
from io import StringIO
import json
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import pandas as pd

from engine.data_sources.finviz_source import FinvizDataSource
from engine.data_sources.sec_source import SECDataSource
from engine.data_sources.transcript_source import TranscriptDataSource


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
RESEARCH_DIR = DATA_DIR / "research"
RAW_DIR = RESEARCH_DIR / "raw"
CACHE_DIR = RESEARCH_DIR / "cache"
FACTS_DIR = RESEARCH_DIR / "facts"
LOGS_DIR = RESEARCH_DIR / "logs"
REVIEW_DIR = RESEARCH_DIR / "review"
CONFIG_DIR = RESEARCH_DIR / "config"
IDENTITY_DIR = RESEARCH_DIR / "identity"

COLLECTION_INDEX_PATH = CACHE_DIR / "phase1_collection_index.json"
RUN_SUMMARY_PATH = LOGS_DIR / "phase1_run_summary_latest.json"
FACT_STORE_PATH = FACTS_DIR / "phase1_fact_store.jsonl"
OFFICIAL_SOURCE_REGISTRY_PATH = CONFIG_DIR / "official_source_registry.json"
FACT_STATUS_AUDIT_PATH = LOGS_DIR / "phase1c_fact_status_audit.json"
SECURITY_IDENTITY_REGISTRY_PATH = CONFIG_DIR / "security_identity_registry.json"
IDENTITY_HISTORY_REGISTRY_PATH = CONFIG_DIR / "ticker_identity_history.json"
SPCX_IDENTITY_PATH = IDENTITY_DIR / "SPCX_identity.json"

INITIAL_TICKERS = ["CRWD", "NBIS", "OPRA", "VBNK", "ARTV", "SPCX"]

SECURITY_TYPE_BY_TICKER = {
    "CRWD": "operating_company",
    "NBIS": "operating_company",
    "OPRA": "operating_company",
    "RKLB": "operating_company",
    "VBNK": "bank",
    "ARTV": "biotechnology",
    "SPCX": "etf_fund",
}

COVERAGE_TARGETS = {
    "CRWD": 75.0,
    "NBIS": 70.0,
    "OPRA": 70.0,
    "RKLB": 70.0,
    "VBNK": 70.0,
    "ARTV": 65.0,
    "SPCX": 70.0,
}

TICKER_REQUIRED_FIELDS = {
    "CRWD": [
        "revenue",
        "arr",
        "subscription_revenue",
        "gross_margin",
        "operating_margin",
        "free_cash_flow",
        "free_cash_flow_margin",
        "customer_count",
        "retention",
        "stock_based_compensation",
        "diluted_share_count",
        "cash",
        "debt",
        "guidance",
    ],
    "NBIS": [
        "revenue",
        "revenue_by_segment",
        "ai_infrastructure_revenue",
        "gross_margin",
        "operating_loss",
        "capital_expenditures",
        "cash",
        "debt",
        "share_count",
        "customer_concentration",
        "guidance",
        "stock_based_compensation",
        "share_count_change",
    ],
    "OPRA": [
        "revenue",
        "revenue_growth",
        "advertising_revenue",
        "search_revenue",
        "gross_margin",
        "operating_margin",
        "free_cash_flow",
        "cash",
        "debt",
        "share_count",
        "buybacks",
        "dividends",
        "guidance",
    ],
    "RKLB": [
        "revenue",
        "gross_margin",
        "operating_income",
        "cash",
        "debt",
        "share_count",
        "backlog",
        "guidance",
    ],
    "VBNK": [
        "tangible_common_equity",
        "tangible_book_value",
        "tbv_per_share",
        "book_value_per_share",
        "roe",
        "rotce",
        "net_interest_income",
        "net_interest_margin",
        "loans",
        "loan_growth",
        "deposits",
        "deposit_growth",
        "nonperforming_assets",
        "charge_offs",
        "provision_for_credit_losses",
        "allowance_for_credit_losses",
        "cet1",
        "tier1_capital_ratio",
        "total_capital_ratio",
        "common_equity",
        "diluted_share_count",
        "guidance",
    ],
    "ARTV": [
        "cash",
        "marketable_securities",
        "debt",
        "quarterly_operating_cash_flow",
        "quarterly_operating_expense",
        "research_and_development_expense",
        "general_and_administrative_expense",
        "estimated_cash_runway",
        "pipeline_programs",
        "development_stage",
        "trial_phase",
        "enrollment_status",
        "expected_data_readouts",
        "regulatory_designations",
        "partnerships",
        "licensing_agreements",
        "share_count",
        "recent_financing",
        "management_stated_dilution_disclosures",
    ],
    "SPCX": [
        "fund_strategy",
        "fund_type",
        "expense_ratio",
        "net_assets",
        "assets_under_management",
        "fund_inception_date",
        "number_of_holdings",
        "top_ten_holdings",
        "top_ten_concentration",
        "benchmark",
        "average_daily_volume",
        "portfolio_turnover",
        "distribution_yield",
        "fund_sponsor",
        "advisor",
    ],
}

TICKER_OPTIONAL_FIELDS = {
    "CRWD": ["customer_concentration", "buybacks", "share_count_change"],
    "NBIS": ["dilution", "retention", "arr"],
    "OPRA": ["capital_expenditures", "operating_loss"],
    "RKLB": [
        "launch_services_revenue",
        "space_systems_revenue",
        "adjusted_ebitda",
        "spacecraft",
        "electron",
        "neutron",
    ],
    "VBNK": [
        "deposit_mix",
        "nonperforming_loans",
        "net_interest_margin_credit_assets",
        "net_interest_margin_other",
        "allowance_for_credit_losses_loans",
        "allowance_for_credit_losses_off_balance_sheet",
        "allowance_for_credit_losses_stage_1",
        "allowance_for_credit_losses_stage_2",
        "allowance_for_credit_losses_stage_3",
        "credit_assets_net_of_allowance",
        "gross_impaired_loans",
        "impaired_loans",
        "stage_3_loans",
    ],
    "ARTV": ["warrants", "atm_facilities", "shelf_registrations", "indications"],
    "SPCX": [
        "complete_holdings_list",
        "sector_exposure",
        "geographic_exposure",
        "market_cap_exposure",
        "historical_returns",
        "historical_volatility",
        "maximum_drawdown",
        "liquidity_metrics",
        "overlap_with_existing_holdings",
    ],
}

OFFICIAL_SOURCE_URLS = {
    "CRWD": {
        "official_ir_page": "https://www.crowdstrike.com/",
    },
    "NBIS": {
        "official_ir_page": "https://nebius.com/",
    },
    "OPRA": {
        "official_ir_page": "https://www.opera.com/",
    },
    "VBNK": {
        "official_ir_page": "https://www.versabank.com/investor-relations/",
        "official_bank_regulatory_materials": "https://www.versabank.com/investors/",
    },
    "ARTV": {
        "official_ir_page": "https://www.artivabio.com/",
        "official_pipeline_page": "https://www.artivabio.com/nk-cell-therapy-pipeline/",
    },
    "SPCX": {
        "official_fund_sponsor_page": "https://www.defianceetfs.com/spcx/",
        "official_etf_fact_sheet": "https://www.defianceetfs.com/spcx/",
        "official_fund_holdings": "https://www.defianceetfs.com/spcx/",
    },
}

# normalized_field -> taxonomy aliases and preferred unit families.
XBRL_FIELD_MAPPINGS = {
    "revenue": {
        "aliases": {
            "us-gaap": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
            "ifrs-full": ["Revenue", "RevenueFromContractsWithCustomers", "RevenueFromRenderingOfServices"],
        },
        "units": ["USD"],
    },
    "advertising_revenue": {
        "aliases": {"us-gaap": ["AdvertisingRevenue"], "ifrs-full": ["AdvertisingRevenue"]},
        "units": ["USD"],
    },
    "gross_profit": {
        "aliases": {"us-gaap": ["GrossProfit"], "ifrs-full": ["GrossProfit"]},
        "units": ["USD"],
    },
    "operating_income": {
        "aliases": {
            "us-gaap": ["OperatingIncomeLoss"],
            "ifrs-full": ["ProfitLossFromOperatingActivities"],
        },
        "units": ["USD"],
    },
    "operating_loss": {
        "aliases": {
            "us-gaap": ["OperatingIncomeLoss"],
            "ifrs-full": ["ProfitLossFromOperatingActivities"],
        },
        "units": ["USD"],
    },
    "adjusted_ebitda": {
        "aliases": {
            "us-gaap": ["OperatingIncomeLoss"],
            "ifrs-full": ["ProfitLossFromOperatingActivities"],
        },
        "units": ["USD"],
    },
    "free_cash_flow": {
        "aliases": {
            "us-gaap": ["NetCashProvidedByUsedInOperatingActivities", "OperatingActivitiesCashFlows"],
            "ifrs-full": ["CashFlowsFromUsedInOperatingActivities"],
        },
        "units": ["USD"],
    },
    "capital_expenditures": {
        "aliases": {
            "us-gaap": ["PaymentsForCapitalExpenditures", "PaymentsToAcquirePropertyPlantAndEquipment"],
            "ifrs-full": ["PurchaseOfPropertyPlantAndEquipment", "PaymentsToAcquirePropertyPlantAndEquipment"],
        },
        "units": ["USD"],
    },
    "stock_based_compensation": {
        "aliases": {
            "us-gaap": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
            "ifrs-full": ["SharebasedPaymentExpense", "AdjustmentsForSharebasedPayments"],
        },
        "units": ["USD"],
    },
    "cash": {
        "aliases": {
            "us-gaap": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments"],
            "ifrs-full": ["CashAndCashEquivalents"],
        },
        "units": ["USD"],
    },
    "marketable_securities": {
        "aliases": {
            "us-gaap": [
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                "MarketableSecuritiesCurrent",
                "ShortTermInvestments",
                "DebtSecuritiesAvailableForSaleAmortizedCostAllowanceForCreditLossExcludingAccruedInterestCurrent",
            ],
            "ifrs-full": ["CurrentFinancialAssetsAtFairValueThroughProfitOrLossClassifiedAsHeldForTrading"],
        },
        "units": ["USD"],
    },
    "debt": {
        "aliases": {
            "us-gaap": ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
            "ifrs-full": ["Borrowings", "LoansAndBorrowings", "DepositsFromBanks"],
        },
        "units": ["USD"],
    },
    "common_equity": {
        "aliases": {
            "us-gaap": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
            "ifrs-full": ["Equity"],
        },
        "units": ["USD"],
    },
    "diluted_share_count": {
        "aliases": {
            "us-gaap": ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"],
            "ifrs-full": ["AdjustedWeightedAverageShares"],
            "dei": ["EntityCommonStockSharesOutstanding"],
        },
        "units": ["shares"],
    },
    "share_count": {
        "aliases": {
            "us-gaap": ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"],
            "ifrs-full": ["AdjustedWeightedAverageShares"],
            "dei": ["EntityCommonStockSharesOutstanding"],
        },
        "units": ["shares"],
    },
    "net_interest_income": {
        "aliases": {"ifrs-full": ["InterestRevenueExpense", "FinanceIncome"]},
        "units": ["USD"],
    },
    "deposits": {
        "aliases": {"ifrs-full": ["DepositsFromBanks", "CurrentDepositsFromCustomers"]},
        "units": ["USD"],
    },
    "loans": {
        "aliases": {"ifrs-full": ["CurrentLoansAndReceivables", "LoansAndReceivables", "LoansAndAdvances"]},
        "units": ["USD"],
    },
    "quarterly_operating_expense": {
        "aliases": {"us-gaap": ["OperatingExpenses"], "ifrs-full": ["OperatingExpenses"]},
        "units": ["USD"],
    },
    "research_and_development_expense": {
        "aliases": {"us-gaap": ["ResearchAndDevelopmentExpense"]},
        "units": ["USD"],
    },
    "general_and_administrative_expense": {
        "aliases": {"us-gaap": ["GeneralAndAdministrativeExpense"]},
        "units": ["USD"],
    },
    "quarterly_operating_cash_flow": {
        "aliases": {
            "us-gaap": ["NetCashProvidedByUsedInOperatingActivities"],
            "ifrs-full": ["CashFlowsFromUsedInOperatingActivities"],
        },
        "units": ["USD"],
    },
    "goodwill": {
        "aliases": {"ifrs-full": ["Goodwill"]},
        "units": ["CAD", "USD"],
    },
    "intangible_assets": {
        "aliases": {"ifrs-full": ["IntangibleAssetsOtherThanGoodwill"]},
        "units": ["CAD", "USD"],
    },
    "dividends": {
        "aliases": {
            "ifrs-full": [
                "DividendsPaid",
                "DividendsPaidClassifiedAsFinancingActivities",
            ]
        },
        "units": ["USD"],
    },
    "customer_concentration": {
        "aliases": {
            "us-gaap": ["ConcentrationRiskPercentage1"],
        },
        "units": ["pure", "percent"],
    },
}

RKLB_TABLE_FIELD_MAP = {
    "backlog": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
    "launch_services_revenue": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
    "space_systems_revenue": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
    "adjusted_ebitda": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
}


VBNK_TABLE_FIELD_MAP = {
    "book_value_per_share": {
        "accepted_labels": ["Book value per common share"],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "net_interest_margin": {
        "accepted_labels": [],
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "duration",
        "calculation_allowed": False,
    },
    "net_interest_margin_credit_assets": {
        "accepted_labels": [],
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "duration",
        "calculation_allowed": False,
    },
    "net_interest_margin_other": {
        "accepted_labels": [],
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "duration",
        "calculation_allowed": False,
    },
    "provision_for_credit_losses": {
        "accepted_labels": ["Provision for credit losses", "Provision for credit losses (note 5)"],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "duration",
        "calculation_allowed": False,
    },
    "allowance_for_credit_losses": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "allowance_for_credit_losses_loans": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "allowance_for_credit_losses_off_balance_sheet": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "allowance_for_credit_losses_stage_1": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "allowance_for_credit_losses_stage_2": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "allowance_for_credit_losses_stage_3": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "credit_assets_net_of_allowance": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "cet1": {
        "accepted_labels": ["Common Equity Tier 1 (CET1) ratio", "Common Equity Tier 1 capital ratio"],
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "tier1_capital_ratio": {
        "accepted_labels": ["Tier 1 capital ratio"],
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "total_capital_ratio": {
        "accepted_labels": ["Total capital ratio"],
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "instant",
        "calculation_allowed": False,
    },
    "tangible_common_equity": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": True,
    },
    "tangible_book_value": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": True,
    },
    "tbv_per_share": {
        "accepted_labels": [],
        "expected_unit": "CAD",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": True,
    },
    "loan_growth": {
        "accepted_labels": [],
        "expected_unit": "percent",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": True,
    },
    "deposit_growth": {
        "accepted_labels": [],
        "expected_unit": "percent",
        "expected_currency": "CAD",
        "period_type": "instant",
        "calculation_allowed": True,
    },
}

VBNK_REQUIRED_NIM_EXACT_LABELS = {
    "net interest margin",
    "net interest margin (%)",
}

VBNK_NIM_REJECT_TOKENS = {
    "credit assets",
    "digital deposit receipts",
    "segment",
    "portfolio",
    "yield",
    "spread",
}

VBNK_REQUIRED_ALLOWANCE_EXACT_LABELS = {
    "allowance for credit losses",
    "allowance for expected credit losses",
    "total allowance for credit losses",
    "total allowance for expected credit losses",
}

CRWD_TABLE_FIELD_MAP = {
    "arr": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "instant",
    },
    "subscription_revenue": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
    "retention": {
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "duration",
    },
}

OPRA_TABLE_FIELD_MAP = {
    "advertising_revenue": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
    "search_revenue": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
}

NBIS_TABLE_FIELD_MAP = {
    "ai_infrastructure_revenue": {
        "expected_unit": "USD",
        "expected_currency": "USD",
        "period_type": "duration",
    },
    "customer_concentration": {
        "expected_unit": "percent",
        "expected_currency": "",
        "period_type": "duration",
    },
}

ARTV_TABLE_FIELD_MAP = {
    "pipeline_programs": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "development_stage": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "trial_phase": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "enrollment_status": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "expected_data_readouts": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "regulatory_designations": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "partnerships": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "licensing_agreements": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "recent_financing": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
    "management_stated_dilution_disclosures": {
        "expected_unit": "text",
        "expected_currency": "",
        "period_type": "duration",
    },
}


def _normalize_vbnk_row_label(label: str) -> str:
    text = html.unescape(str(label or "")).strip()
    text = re.sub(r"\s+", " ", text)
    # Strip trailing footnote markers while preserving original label separately.
    text = re.sub(r"[\*\u2020\u2021\u00a7]+$", "", text).strip()
    return text


def _normalize_crwd_row_label(label: str) -> str:
    text = html.unescape(str(label or "")).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\*\u2020\u2021\u00a7]+$", "", text).strip()
    return text


def _classify_crwd_table_row_label(original_label: str) -> List[Dict[str, str]]:
    normalized = _normalize_crwd_row_label(original_label)
    low = normalized.lower()
    out: List[Dict[str, str]] = []

    if "annual recurring revenue" in low:
        out.append(
            {
                "normalized_field": "arr",
                "definition": "annual_recurring_revenue",
                "consolidation_scope": "consolidated_company",
            }
        )

    if "subscription revenue" in low and len(low) <= 80:
        out.append(
            {
                "normalized_field": "subscription_revenue",
                "definition": "subscription_revenue_total",
                "consolidation_scope": "consolidated_company",
            }
        )

    if "dollar-based net retention rate" in low or low == "net retention rate":
        out.append(
            {
                "normalized_field": "retention",
                "definition": "dollar_based_net_retention_rate",
                "consolidation_scope": "consolidated_company",
            }
        )

    return out


def _normalize_opra_row_label(label: str) -> str:
    text = html.unescape(str(label or "")).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\*\u2020\u2021\u00a7]+$", "", text).strip()
    return text


def _classify_opra_table_row_label(original_label: str) -> List[Dict[str, str]]:
    normalized = _normalize_opra_row_label(original_label)
    low = normalized.lower()
    out: List[Dict[str, str]] = []

    if low in {"advertising", "advertising revenue"}:
        out.append(
            {
                "normalized_field": "advertising_revenue",
                "definition": "advertising_revenue_total",
                "consolidation_scope": "consolidated_company",
            }
        )

    if low in {"search", "search revenue"}:
        out.append(
            {
                "normalized_field": "search_revenue",
                "definition": "search_revenue_total",
                "consolidation_scope": "consolidated_company",
            }
        )

    return out


def _normalize_nbis_row_label(label: str) -> str:
    text = html.unescape(str(label or "")).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\*\u2020\u2021\u00a7]+$", "", text).strip()
    return text


def _normalize_rklb_row_label(label: str) -> str:
    text = html.unescape(str(label or "")).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\*\u2020\u2021\u00a7]+$", "", text).strip()
    return text


def _classify_rklb_table_row_label(original_label: str) -> List[Dict[str, str]]:
    normalized = _normalize_rklb_row_label(original_label)
    low = normalized.lower()
    out: List[Dict[str, str]] = []

    if "backlog" in low:
        out.append(
            {
                "normalized_field": "backlog",
                "definition": "order_backlog",
                "consolidation_scope": "aerospace_and_defense",
            }
        )

    if "launch services revenue" in low or low == "launch services":
        out.append(
            {
                "normalized_field": "launch_services_revenue",
                "definition": "launch_services_revenue",
                "consolidation_scope": "aerospace_and_defense",
            }
        )

    if "space systems revenue" in low or low == "space systems":
        out.append(
            {
                "normalized_field": "space_systems_revenue",
                "definition": "space_systems_revenue",
                "consolidation_scope": "aerospace_and_defense",
            }
        )

    if "adjusted ebitda" in low:
        out.append(
            {
                "normalized_field": "adjusted_ebitda",
                "definition": "adjusted_ebitda",
                "consolidation_scope": "aerospace_and_defense",
            }
        )

    return out


def _extract_rklb_table_frame(df: pd.DataFrame, row: Dict[str, Any], table_index: int) -> List[Dict[str, Any]]:
    extracted = []
    emitted: set[Tuple[str, str, str]] = set()
    sdf = df.astype(str).fillna("")
    for row_index, series in sdf.iterrows():
        values = [str(x).strip() for x in series.tolist()]
        row_label = next((value for value in values if value and _parse_numeric_cell(value) is None), "")
        if not row_label:
            continue

        normalized_label = _normalize_rklb_row_label(row_label)
        classifications = _classify_rklb_table_row_label(normalized_label)
        if not classifications:
            continue

        numeric_candidates = []
        for col_index, cell in enumerate(values[1:], start=1):
            parsed = _parse_numeric_cell(cell)
            if parsed is None:
                continue
            col_label = str(df.columns[col_index]) if col_index < len(df.columns) else ""
            numeric_candidates.append((col_index, parsed, col_label))
        if not numeric_candidates:
            continue

        col_index, parsed_value, col_label = numeric_candidates[0]
        for cls in classifications:
            normalized_field = cls["normalized_field"]
            dedupe_key = (
                normalized_field,
                normalized_label.lower(),
                str(row.get("document_id") or ""),
            )
            if dedupe_key in emitted:
                continue
            emitted.add(dedupe_key)

            spec = RKLB_TABLE_FIELD_MAP.get(normalized_field, {})
            extracted.append(
                {
                    "normalized_field": normalized_field,
                    "original_field": row_label,
                    "definition": cls.get("definition", ""),
                    "value": parsed_value,
                    "unit": str(spec.get("expected_unit") or "USD"),
                    "currency": str(spec.get("expected_currency") or "USD"),
                    "period": str(row.get("document_date") or "latest"),
                    "period_start": "",
                    "period_end": str(row.get("document_date") or ""),
                    "fiscal_period": str(row.get("document_date") or ""),
                    "instant_or_duration": str(spec.get("period_type") or "duration"),
                    "source_document_id": str(row.get("document_id") or ""),
                    "source_url": str(row.get("source_url") or ""),
                    "local_cache_path": str(row.get("local_cache_path") or ""),
                    "document_title": str(row.get("document_title") or ""),
                    "table_title": str(row.get("document_title") or row.get("source_type") or ""),
                    "table_index": str(table_index),
                    "row_label": row_label,
                    "normalized_row_label": normalized_label,
                    "column_label": col_label,
                    "page_number": "",
                    "sheet_name": "",
                    "cell_reference": f"table:{table_index};row:{row_index};col:{col_index}",
                    "matched_text": row_label,
                    "extraction_method": "html_table_row_match",
                    "confidence": 90.0,
                    "fact_status": "verified",
                    "consolidation_scope": cls.get("consolidation_scope", ""),
                }
            )
    return extracted


def _extract_rklb_table_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = Path(str(row.get("local_cache_path") or ""))
    if not path.exists():
        return []
    try:
        tables = pd.read_html(StringIO(path.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        return []

    extracted = []
    for table_index, df in enumerate(tables):
        extracted.extend(_extract_rklb_table_frame(df, row, table_index))
    return extracted


def _extract_nbis_ai_revenue_from_row_text(text: str) -> Optional[float]:
    patterns = [
        r"to\s*(\$[0-9.,]+\s*(?:million|billion|m|b)?)\s+in\s+20[0-9]{2}",
        r"AI cloud business[^$]{0,120}(\$[0-9.,]+\s*(?:million|billion|m|b)?)",
        r"AI infrastructure[^$]{0,120}(\$[0-9.,]+\s*(?:million|billion|m|b)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if not m:
            continue
        value = _parse_human_number(m.group(1))
        if value is not None:
            return value
    return None


def _classify_vbnk_table_row_label(original_label: str) -> List[Dict[str, str]]:
    normalized = _normalize_vbnk_row_label(original_label)
    low = normalized.lower()
    out: List[Dict[str, str]] = []

    if low in VBNK_REQUIRED_NIM_EXACT_LABELS:
        out.append(
            {
                "normalized_field": "net_interest_margin",
                "definition": "consolidated_bank_net_interest_margin",
                "consolidation_scope": "consolidated_bank",
            }
        )
    elif "net interest margin" in low:
        if "credit assets" in low:
            out.append(
                {
                    "normalized_field": "net_interest_margin_credit_assets",
                    "definition": "net_interest_margin_on_credit_assets",
                    "consolidation_scope": "credit_assets",
                }
            )
        elif any(token in low for token in VBNK_NIM_REJECT_TOKENS):
            out.append(
                {
                    "normalized_field": "net_interest_margin_other",
                    "definition": "specialized_net_interest_margin",
                    "consolidation_scope": "specialized_or_segment",
                }
            )

    if low in {"book value per common share", "book value per common share (%)"}:
        out.append(
            {
                "normalized_field": "book_value_per_share",
                "definition": "book_value_per_common_share",
                "consolidation_scope": "consolidated_bank",
            }
        )

    if low in {"common equity tier 1 (cet1) ratio", "common equity tier 1 capital ratio"}:
        out.append(
            {
                "normalized_field": "cet1",
                "definition": "common_equity_tier_1_ratio",
                "consolidation_scope": "consolidated_bank",
            }
        )

    if low == "tier 1 capital ratio":
        out.append(
            {
                "normalized_field": "tier1_capital_ratio",
                "definition": "tier_1_capital_ratio",
                "consolidation_scope": "consolidated_bank",
            }
        )

    if low == "total capital ratio":
        out.append(
            {
                "normalized_field": "total_capital_ratio",
                "definition": "total_capital_ratio",
                "consolidation_scope": "consolidated_bank",
            }
        )

    if low in VBNK_REQUIRED_ALLOWANCE_EXACT_LABELS:
        out.append(
            {
                "normalized_field": "allowance_for_credit_losses",
                "definition": "total_allowance_for_credit_losses",
                "consolidation_scope": "consolidated_bank",
            }
        )
    elif "allowance" in low and "credit losses" in low:
        if "net of allowance" in low or "credit assets" in low:
            out.append(
                {
                    "normalized_field": "credit_assets_net_of_allowance",
                    "definition": "credit_assets_net_of_allowance",
                    "consolidation_scope": "credit_assets",
                }
            )
        elif "loans and advances" in low:
            out.append(
                {
                    "normalized_field": "allowance_for_credit_losses_loans",
                    "definition": "allowance_for_loans_and_advances",
                    "consolidation_scope": "loans_and_advances",
                }
            )
        elif "off-balance-sheet" in low:
            out.append(
                {
                    "normalized_field": "allowance_for_credit_losses_off_balance_sheet",
                    "definition": "allowance_for_off_balance_sheet_exposures",
                    "consolidation_scope": "off_balance_sheet",
                }
            )
        elif "stage 1" in low:
            out.append(
                {
                    "normalized_field": "allowance_for_credit_losses_stage_1",
                    "definition": "allowance_stage_1",
                    "consolidation_scope": "ifrs_stage_1",
                }
            )
        elif "stage 2" in low:
            out.append(
                {
                    "normalized_field": "allowance_for_credit_losses_stage_2",
                    "definition": "allowance_stage_2",
                    "consolidation_scope": "ifrs_stage_2",
                }
            )
        elif "stage 3" in low:
            out.append(
                {
                    "normalized_field": "allowance_for_credit_losses_stage_3",
                    "definition": "allowance_stage_3",
                    "consolidation_scope": "ifrs_stage_3",
                }
            )

    if "provision for credit losses" in low:
        out.append(
            {
                "normalized_field": "provision_for_credit_losses",
                "definition": "provision_expense_for_credit_losses",
                "consolidation_scope": "consolidated_bank",
            }
        )

    if low in {"nonperforming assets", "total nonperforming assets"}:
        out.append(
            {
                "normalized_field": "nonperforming_assets",
                "definition": "nonperforming_assets_total",
                "consolidation_scope": "consolidated_bank",
            }
        )
    if "nonperforming loans" in low:
        out.append(
            {
                "normalized_field": "nonperforming_loans",
                "definition": "nonperforming_loans_total",
                "consolidation_scope": "consolidated_bank",
            }
        )
    if "gross impaired loans" in low:
        out.append(
            {
                "normalized_field": "gross_impaired_loans",
                "definition": "gross_impaired_loans",
                "consolidation_scope": "consolidated_bank",
            }
        )
    elif "impaired loans" in low:
        out.append(
            {
                "normalized_field": "impaired_loans",
                "definition": "impaired_loans",
                "consolidation_scope": "consolidated_bank",
            }
        )
    if "stage 3 loans" in low:
        out.append(
            {
                "normalized_field": "stage_3_loans",
                "definition": "ifrs_stage_3_loans",
                "consolidation_scope": "ifrs_stage_3",
            }
        )

    if "net charge-off" in low or "net charge off" in low:
        out.append(
            {
                "normalized_field": "charge_offs",
                "definition": "net_charge_offs",
                "consolidation_scope": "consolidated_bank",
            }
        )
    elif "gross charge-off" in low or "gross charge off" in low or "write-off" in low or "write off" in low:
        out.append(
            {
                "normalized_field": "charge_offs",
                "definition": "gross_or_write_offs",
                "consolidation_scope": "consolidated_bank",
            }
        )

    return out


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs() -> None:
    for path in [RAW_DIR, CACHE_DIR, FACTS_DIR, LOGS_DIR, REVIEW_DIR, CONFIG_DIR, IDENTITY_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def _stable_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _json_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "document"


def _clean_text(raw: str) -> str:
    text = raw or ""
    text = re.sub(r"<script[\\s\\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()


def _parse_human_number(raw: str) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    s = s.replace("$", "")
    low = s.lower()
    mult = 1.0
    if low.endswith("billion"):
        mult = 1_000_000_000.0
        s = s[: -len("billion")].strip()
    elif low.endswith("million"):
        mult = 1_000_000.0
        s = s[: -len("million")].strip()
    elif low.endswith("thousand"):
        mult = 1_000.0
        s = s[: -len("thousand")].strip()
    elif low.endswith("b"):
        mult = 1_000_000_000.0
        s = s[:-1].strip()
    elif low.endswith("m"):
        mult = 1_000_000.0
        s = s[:-1].strip()
    elif low.endswith("k"):
        mult = 1_000.0
        s = s[:-1].strip()
    try:
        return float(s) * mult
    except ValueError:
        return None


def infer_security_type(ticker: str) -> str:
    normalized = str(ticker or "").strip().upper()
    return SECURITY_TYPE_BY_TICKER.get(normalized, "operating_company")


def required_fields_for_ticker(ticker: str, security_type: str) -> List[str]:
    t = str(ticker or "").upper()
    if t in TICKER_REQUIRED_FIELDS:
        return list(TICKER_REQUIRED_FIELDS[t])
    return []


def optional_fields_for_ticker(ticker: str) -> List[str]:
    return list(TICKER_OPTIONAL_FIELDS.get(str(ticker or "").upper(), []))


def _infer_currency(unit: str) -> str:
    upper = str(unit or "").upper()
    if upper.startswith("USD"):
        return "USD"
    if upper.startswith("CAD"):
        return "CAD"
    return ""


def _build_status_index(facts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    priority = {"verified": 5, "conflicting": 4, "uncertain": 3, "not_applicable": 2, "missing": 1}
    out: Dict[str, Dict[str, Any]] = {}
    for fact in facts:
        field = str(fact.get("normalized_field") or fact.get("field") or "")
        if not field:
            continue
        status = str(fact.get("fact_status") or "missing")
        current = out.get(field)
        if current is None or priority.get(status, 0) > priority.get(str(current.get("fact_status") or "missing"), 0):
            out[field] = fact
    return out


def _audit_reason(old_fact: Dict[str, Any], new_fact: Optional[Dict[str, Any]]) -> str:
    if not new_fact:
        return "Field missing after Phase 1C reprocessing"
    old_status = str(old_fact.get("fact_status") or "")
    new_status = str(new_fact.get("fact_status") or "")
    if old_status == "verified" and new_status == "uncertain":
        return "Narrative regex match no longer auto-verifies without exact structured or table lineage"
    if old_status == "verified" and new_status == "missing":
        return "Previous match could not be confirmed with exact per-document source attribution"
    if old_fact.get("source_document_id") != new_fact.get("source_document_id"):
        return "Source attribution corrected to exact matching document"
    return "Status recalculated under Phase 1C lineage and verification rules"


def _build_fact_status_audit(previous_facts: Dict[str, List[Dict[str, Any]]], current_facts: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ticker, old_rows in previous_facts.items():
        old_index = _build_status_index([r for r in old_rows if str(r.get("extraction_method") or "") == "official_document_regex"])
        current_index = _build_status_index(current_facts.get(ticker, []))
        for field, old_fact in old_index.items():
            if str(old_fact.get("fact_status") or "") != "verified":
                continue
            new_fact = current_index.get(field)
            rows.append(
                {
                    "ticker": ticker,
                    "field": field,
                    "old_status": old_fact.get("fact_status"),
                    "new_status": (new_fact or {}).get("fact_status", "missing"),
                    "old_source": old_fact.get("source_document_id") or old_fact.get("source_url") or "",
                    "new_source": (new_fact or {}).get("source_document_id") or (new_fact or {}).get("source_url") or "",
                    "reason_for_change": _audit_reason(old_fact, new_fact),
                }
            )
    for ticker, new_rows in current_facts.items():
        if not new_rows or not all(str(f.get("extraction_method") or "") == "identity_gate" for f in new_rows):
            continue
        old_index = _build_status_index(previous_facts.get(ticker, []))
        current_index = _build_status_index(new_rows)
        for field, new_fact in current_index.items():
            old_fact = old_index.get(field, {})
            rows.append(
                {
                    "ticker": ticker,
                    "field": field,
                    "old_status": old_fact.get("fact_status", "unknown"),
                    "new_status": new_fact.get("fact_status", "missing"),
                    "old_source": old_fact.get("source_document_id") or old_fact.get("source_url") or "",
                    "new_source": new_fact.get("source_document_id") or new_fact.get("source_url") or "",
                    "reason_for_change": f"Identity-gated because {ticker} is not identity-verified; fact extraction blocked.",
                }
            )
    return rows


def _validate_official_url(url: str, expected_terms: List[str]) -> Dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        response = session.get(url, timeout=12, allow_redirects=True)
        lower = response.text.lower()
        issuer_match = any(term.lower() in lower for term in expected_terms if term)
        return {
            "official_url": url,
            "verified_at": _utc_now_iso(),
            "http_status": response.status_code,
            "redirected_url": response.url,
            "issuer_or_sponsor_match": issuer_match,
            "active": response.status_code == 200 and issuer_match,
            "notes": "validated" if response.status_code == 200 and issuer_match else "url reachable but identity mismatch" if response.status_code == 200 else f"http {response.status_code}",
        }
    except Exception as exc:
        return {
            "official_url": url,
            "verified_at": _utc_now_iso(),
            "http_status": 0,
            "redirected_url": "",
            "issuer_or_sponsor_match": False,
            "active": False,
            "notes": str(exc),
        }


def _expected_identity_terms(ticker: str) -> List[str]:
    return {
        "CRWD": ["crowdstrike", "falcon"],
        "NBIS": ["nebius"],
        "OPRA": ["opera"],
        "RKLB": ["rocket lab", "rklb", "electron", "neutron"],
        "VBNK": ["versabank"],
        "ARTV": ["artiva"],
        "SPCX": ["defiance", "spcx", "exchange-traded fund", "etf"],
    }.get(str(ticker or "").upper(), [str(ticker or "")])


def _load_sec_company_ticker_records() -> List[Dict[str, Any]]:
    url = "https://www.sec.gov/files/company_tickers.json"
    response = requests.get(url, headers={"User-Agent": "McLeod Capital Research Engine 1.0 (mason@mcleodcapital.com)"}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return [item for item in payload.values() if isinstance(item, dict)]
    return []


def _lookup_sec_company_ticker_record(ticker: str) -> Optional[Dict[str, Any]]:
    target = str(ticker or "").upper().strip()
    for row in _load_sec_company_ticker_records():
        if str(row.get("ticker") or "").upper().strip() == target:
            return row
    return None


def _fetch_sec_browse_identity(cik: str) -> Dict[str, Any]:
    cleaned = str(int(str(cik)))
    url = f"https://www.sec.gov/Archives/edgar/browse/?CIK={cleaned}&owner=exclude&action=getcompany"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        response.raise_for_status()
        text = _clean_text(response.text)
        exchange = ""
        if " on Nasdaq" in text:
            exchange = "Nasdaq"
        elif " on Nyse" in text:
            exchange = "NYSE"
        return {"browse_url": url, "exchange": exchange, "raw_excerpt": text[:400]}
    except Exception as exc:
        return {"browse_url": url, "exchange": "", "error": str(exc), "raw_excerpt": ""}


def _infer_reporting_currency_from_companyfacts(ticker: str) -> str:
    path = RAW_DIR / ticker / "sec_companyfacts.json"
    payload = _json_load(path, {})
    facts = (payload.get("facts") or {}) if isinstance(payload, dict) else {}
    for _, concept_map in facts.items():
        if not isinstance(concept_map, dict):
            continue
        for _, concept in concept_map.items():
            units = (concept or {}).get("units") or {}
            for unit_name in units.keys():
                currency = _infer_currency(unit_name)
                if currency:
                    return currency
    return ""


def _infer_primary_filing_system(submissions: Dict[str, Any]) -> Tuple[str, bool, str]:
    recent = ((submissions.get("filings") or {}).get("recent") or {}) if isinstance(submissions, dict) else {}
    forms = [str(x or "").upper() for x in (recent.get("form") or [])]
    if any(f == "40-F" for f in forms):
        return "SEC foreign issuer (40-F/6-K)", True, "Canada"
    if any(f == "20-F" for f in forms):
        return "SEC foreign issuer (20-F/6-K)", True, "Foreign"
    if any(f == "10-K" for f in forms):
        return "SEC domestic issuer (10-K/10-Q)", False, "United States"
    return "SEC filings", False, ""


def _forms_from_submissions(submissions: Dict[str, Any]) -> List[str]:
    recent = ((submissions.get("filings") or {}).get("recent") or {}) if isinstance(submissions, dict) else {}
    return [str(x or "").upper() for x in (recent.get("form") or [])]


def _infer_security_type_from_forms(forms: List[str]) -> str:
    fund_markers = {"N-CEN", "N-CSR", "N-CSRS", "NPORT-P", "NPORT-EX", "497", "485BPOS", "485APOS"}
    if any(form in fund_markers for form in forms):
        return "etf_fund"
    return "operating_company"


def _load_identity_history_registry() -> Dict[str, Any]:
    payload = _json_load(IDENTITY_HISTORY_REGISTRY_PATH, {})
    return payload if isinstance(payload, dict) else {}


def _identity_candidates_for_ticker(ticker: str, history_registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = history_registry.get(ticker, []) if isinstance(history_registry, dict) else []
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "name": str(row.get("name") or ""),
                "sec_cik": str(row.get("sec_cik") or ""),
                "security_type": str(row.get("security_type") or ""),
                "ticker": str(row.get("ticker") or ticker).upper(),
                "effective_from": str(row.get("effective_from") or ""),
                "effective_to": str(row.get("effective_to") or ""),
                "current": bool(row.get("current")),
                "confidence": float(row.get("confidence") or 0.0),
                "status": str(row.get("status") or "historical"),
                "notes": str(row.get("notes") or ""),
            }
        )
    return out


def _select_canonical_identity(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    current = [c for c in candidates if c.get("current")]
    if current:
        return current[0]
    open_ended = [c for c in candidates if not c.get("effective_to")]
    if open_ended:
        return sorted(open_ended, key=lambda c: str(c.get("effective_from") or ""), reverse=True)[0]
    return sorted(candidates, key=lambda c: str(c.get("effective_to") or c.get("effective_from") or ""), reverse=True)[0]


def _resolve_identity_lifecycle(
    ticker: str,
    expected_security_type: str,
    legal_name: str,
    sec_cik: str,
    forms: List[str],
    history_registry: Dict[str, Any],
) -> Dict[str, Any]:
    sec_inferred_type = _infer_security_type_from_forms(forms)
    candidates = _identity_candidates_for_ticker(ticker, history_registry)
    canonical = _select_canonical_identity(candidates)
    lifecycle = "accept_current"
    status = "verified"
    confidence = 0.9
    notes = ""

    if canonical:
        canonical_cik = str(canonical.get("sec_cik") or "")
        canonical_name = str(canonical.get("name") or "")
        canonical_type = str(canonical.get("security_type") or expected_security_type)
        if canonical_cik and sec_cik and canonical_cik != sec_cik:
            status = "ticker_reassigned"
            lifecycle = "redirect"
            confidence = 0.99
            notes = (
                f"Current SEC mapping for {ticker} points to CIK {sec_cik} ({legal_name}) "
                f"while canonical history maps to CIK {canonical_cik} ({canonical_name})."
            )
        elif canonical_type and expected_security_type and canonical_type != expected_security_type:
            status = "ticker_reassigned"
            lifecycle = "redirect"
            confidence = 0.99
            notes = (
                f"Ticker {ticker} canonical type is {canonical_type}, which differs from expected {expected_security_type}."
            )
        else:
            status = "verified"
            lifecycle = "multi_identity_history" if len(candidates) > 1 else "accept_current"
            confidence = max(float(canonical.get("confidence") or 0.9), 0.9)
            notes = "Historical identity records found; canonical entry selected." if len(candidates) > 1 else ""
    else:
        if expected_security_type != sec_inferred_type:
            status = "ticker_reassigned"
            lifecycle = "reject_current_mapping"
            confidence = 0.99
            notes = (
                f"Expected security type {expected_security_type}, but SEC filing profile implies {sec_inferred_type} "
                f"for {legal_name}."
            )

    return {
        "identity_status": status,
        "identity_confidence": confidence,
        "identity_notes": notes,
        "identity_resolution": lifecycle,
        "canonical_identity": canonical or {},
        "historical_identities": candidates,
        "sec_inferred_security_type": sec_inferred_type,
    }


def _resolve_security_identity(ticker: str) -> Dict[str, Any]:
    ticker = str(ticker or "").upper().strip()
    submissions = _json_load(RAW_DIR / ticker / "sec_submissions.json", {})
    company_row = _lookup_sec_company_ticker_record(ticker)
    sec_cik = ""
    if company_row and company_row.get("cik_str") is not None:
        sec_cik = f"{int(company_row['cik_str']):010d}"
    elif submissions.get("cik"):
        sec_cik = str(submissions.get("cik"))
    browse = _fetch_sec_browse_identity(sec_cik) if sec_cik else {"browse_url": "", "exchange": "", "raw_excerpt": ""}
    filing_system, foreign_issuer, jurisdiction = _infer_primary_filing_system(submissions)
    reporting_currency = _infer_reporting_currency_from_companyfacts(ticker)
    legal_name = str(submissions.get("name") or (company_row or {}).get("title") or ticker)
    forms = _forms_from_submissions(submissions)
    history_registry = _load_identity_history_registry()

    security_type = infer_security_type(ticker)
    official_product_url = OFFICIAL_SOURCE_URLS.get(ticker, {}).get("official_product_url", "")
    official_ir_url = OFFICIAL_SOURCE_URLS.get(ticker, {}).get("official_ir_page", "")

    if ticker == "VBNK":
        security_type = "bank"
        jurisdiction = "Canada"
        reporting_currency = reporting_currency or "CAD"
    elif ticker in {"NBIS", "OPRA"}:
        security_type = "operating_company"
        jurisdiction = "Foreign"
        reporting_currency = reporting_currency or "USD"
    elif ticker in {"CRWD", "ARTV"}:
        security_type = "operating_company"
        jurisdiction = "United States"
        reporting_currency = reporting_currency or "USD"

    lifecycle = _resolve_identity_lifecycle(
        ticker=ticker,
        expected_security_type=security_type,
        legal_name=legal_name,
        sec_cik=sec_cik,
        forms=forms,
        history_registry=history_registry,
    )

    return {
        "ticker": ticker,
        "legal_name": legal_name,
        "security_type": security_type,
        "exchange": browse.get("exchange") or "",
        "reporting_jurisdiction": jurisdiction,
        "reporting_currency": reporting_currency,
        "sec_cik": sec_cik,
        "foreign_issuer_status": foreign_issuer,
        "primary_filing_system": filing_system,
        "official_ir_url": official_ir_url,
        "official_product_url": official_product_url,
        "identity_sources": [
            {"type": "sec_company_tickers", "value": company_row or {}},
            {"type": "sec_submissions", "value": {"name": submissions.get("name"), "cik": submissions.get("cik")}},
            {"type": "sec_browse", "value": browse},
        ],
        "identity_confidence": lifecycle.get("identity_confidence", 0.0),
        "identity_status": lifecycle.get("identity_status", "unresolved"),
        "verified_at": _utc_now_iso(),
        "identity_notes": lifecycle.get("identity_notes", ""),
        "identity_resolution": lifecycle.get("identity_resolution", "accept_current"),
        "canonical_identity": lifecycle.get("canonical_identity", {}),
        "historical_identities": lifecycle.get("historical_identities", []),
        "sec_inferred_security_type": lifecycle.get("sec_inferred_security_type", ""),
    }


def _build_security_identity_registry(tickers: List[str]) -> Dict[str, Any]:
    registry = {ticker: _resolve_security_identity(ticker) for ticker in tickers}
    _json_dump(SECURITY_IDENTITY_REGISTRY_PATH, registry)
    spcx = registry.get("SPCX") or {}
    spcx_identity = {
        "ticker": "SPCX",
        "security_name": spcx.get("legal_name", ""),
        "security_type": spcx.get("security_type", ""),
        "exchange": spcx.get("exchange", ""),
        "cusip": "",
        "sponsor": "",
        "advisor": "",
        "issuer_name": spcx.get("legal_name", ""),
        "sec_cik": spcx.get("sec_cik", ""),
        "sec_series_id": "",
        "sec_class_id": "",
        "operating_status": "active" if spcx.get("identity_status") == "verified" else "ticker_reassigned",
        "official_product_url": spcx.get("official_product_url", ""),
        "official_filing_url": ((spcx.get("identity_sources") or [{}])[-1] or {}).get("value", {}).get("browse_url", ""),
        "identity_sources": spcx.get("identity_sources", []),
        "identity_confidence": spcx.get("identity_confidence", 0.0),
        "identity_status": spcx.get("identity_status", "unresolved"),
        "identity_resolution": spcx.get("identity_resolution", "accept_current"),
        "canonical_identity": spcx.get("canonical_identity", {}),
        "historical_identities": spcx.get("historical_identities", []),
        "identity_notes": spcx.get("identity_notes", ""),
        "verified_at": spcx.get("verified_at", _utc_now_iso()),
    }
    _json_dump(SPCX_IDENTITY_PATH, spcx_identity)
    return registry


def _parse_numeric_cell(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()$")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _discover_vbnk_exhibit_links(row: Dict[str, Any]) -> List[Dict[str, str]]:
    path = Path(str(row.get("local_cache_path") or ""))
    if not path.exists():
        return []
    html = path.read_text(encoding="utf-8", errors="ignore")
    base = str(row.get("source_url") or "")
    base_dir = base.rsplit("/", 1)[0] + "/" if "/" in base else base
    links = []
    for href, title in re.findall(r'<a href="([^"]+\.(?:htm|html|pdf|xlsx|xls|csv|json))"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
        clean_title = _clean_text(title)
        final_url = href if href.startswith("http") else base_dir + href
        lower = clean_title.lower()
        document_type = "other"
        if "interim consolidated financial statements" in lower or "consolidated financial statements" in lower:
            document_type = "financial_statements"
        elif "management" in lower and "discussion" in lower:
            document_type = "mda"
        elif "press release" in lower:
            document_type = "earnings_release"
        elif "annual information form" in lower:
            document_type = "annual_information_form"
        links.append(
            {
                "source_page_url": base,
                "document_url": href,
                "final_url": final_url,
                "document_title": clean_title,
                "document_type": document_type,
            }
        )
    return links


def _extract_vbnk_table_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = Path(str(row.get("local_cache_path") or ""))
    if not path.exists():
        return []
    try:
        tables = pd.read_html(StringIO(path.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        return []
    extracted = []
    for table_index, df in enumerate(tables):
        sdf = df.astype(str).fillna("")
        for row_index, series in sdf.iterrows():
            values = [str(x).strip() for x in series.tolist()]
            row_label = next((value for value in values if value and _parse_numeric_cell(value) is None), "")
            if not row_label:
                continue
            normalized_label = _normalize_vbnk_row_label(row_label)
            classifications = _classify_vbnk_table_row_label(normalized_label)
            if not classifications:
                continue
            numeric_candidates = []
            for col_index, cell in enumerate(values[1:], start=1):
                parsed = _parse_numeric_cell(cell)
                if parsed is not None:
                    numeric_candidates.append((col_index, parsed, str(df.columns[col_index]) if col_index < len(df.columns) else ""))
            if not numeric_candidates:
                continue
            col_index, parsed_value, col_label = numeric_candidates[0]
            unit = ""
            if "%" in " ".join(values):
                unit = "percent"
            elif "$" in " ".join(values):
                unit = "CAD"

            for cls in classifications:
                normalized_field = cls["normalized_field"]
                spec = VBNK_TABLE_FIELD_MAP.get(normalized_field, {})
                chosen_unit = spec.get("expected_unit") or unit
                chosen_currency = spec.get("expected_currency") or ("CAD" if chosen_unit == "CAD" else "")
                extracted.append(
                    {
                        "normalized_field": normalized_field,
                        "original_field": row_label,
                        "definition": cls.get("definition", ""),
                        "value": parsed_value,
                        "unit": chosen_unit,
                        "currency": chosen_currency,
                        "period": str(row.get("document_date") or "latest"),
                        "period_start": "",
                        "period_end": str(row.get("document_date") or ""),
                        "fiscal_period": str(row.get("document_date") or ""),
                        "instant_or_duration": spec.get("period_type", ""),
                        "source_document_id": str(row.get("document_id") or ""),
                        "source_url": str(row.get("source_url") or ""),
                        "local_cache_path": str(row.get("local_cache_path") or ""),
                        "document_title": str(row.get("document_title") or ""),
                        "table_title": str(row.get("document_title") or row.get("source_type") or ""),
                        "table_index": str(table_index),
                        "row_label": row_label,
                        "normalized_row_label": normalized_label,
                        "column_label": col_label,
                        "page_number": "",
                        "sheet_name": "",
                        "cell_reference": f"table:{table_index};row:{row_index};col:{col_index}",
                        "matched_text": row_label,
                        "extraction_method": "html_table_row_match",
                        "confidence": 90.0,
                        "fact_status": "verified",
                        "consolidation_scope": cls.get("consolidation_scope", ""),
                    }
                )
    return extracted


def _extract_crwd_table_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = Path(str(row.get("local_cache_path") or ""))
    if not path.exists():
        return []
    try:
        tables = pd.read_html(StringIO(path.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        return []

    extracted = []
    emitted: set[Tuple[str, str, str]] = set()
    for table_index, df in enumerate(tables):
        sdf = df.astype(str).fillna("")
        for row_index, series in sdf.iterrows():
            values = [str(x).strip() for x in series.tolist()]
            row_label = next((value for value in values if value and _parse_numeric_cell(value) is None), "")
            if not row_label:
                continue

            normalized_label = _normalize_crwd_row_label(row_label)
            classifications = _classify_crwd_table_row_label(normalized_label)
            if not classifications:
                continue

            numeric_candidates = []
            for col_index, cell in enumerate(values[1:], start=1):
                parsed = _parse_numeric_cell(cell)
                if parsed is None:
                    continue
                col_label = str(df.columns[col_index]) if col_index < len(df.columns) else ""
                numeric_candidates.append((col_index, parsed, col_label))
            if not numeric_candidates:
                continue

            col_index, parsed_value, col_label = numeric_candidates[0]
            for cls in classifications:
                normalized_field = cls["normalized_field"]
                dedupe_key = (
                    normalized_field,
                    normalized_label.lower(),
                    str(row.get("document_id") or ""),
                )
                if dedupe_key in emitted:
                    continue
                emitted.add(dedupe_key)

                spec = CRWD_TABLE_FIELD_MAP.get(normalized_field, {})
                extracted.append(
                    {
                        "normalized_field": normalized_field,
                        "original_field": row_label,
                        "definition": cls.get("definition", ""),
                        "value": parsed_value,
                        "unit": str(spec.get("expected_unit") or ""),
                        "currency": str(spec.get("expected_currency") or ""),
                        "period": str(row.get("document_date") or "latest"),
                        "period_start": "",
                        "period_end": str(row.get("document_date") or ""),
                        "fiscal_period": str(row.get("document_date") or ""),
                        "instant_or_duration": str(spec.get("period_type") or ""),
                        "source_document_id": str(row.get("document_id") or ""),
                        "source_url": str(row.get("source_url") or ""),
                        "local_cache_path": str(row.get("local_cache_path") or ""),
                        "document_title": str(row.get("document_title") or ""),
                        "table_title": str(row.get("document_title") or row.get("source_type") or ""),
                        "table_index": str(table_index),
                        "row_label": row_label,
                        "normalized_row_label": normalized_label,
                        "column_label": col_label,
                        "page_number": "",
                        "sheet_name": "",
                        "cell_reference": f"table:{table_index};row:{row_index};col:{col_index}",
                        "matched_text": row_label,
                        "extraction_method": "html_table_row_match",
                        "confidence": 90.0,
                        "fact_status": "verified",
                        "consolidation_scope": cls.get("consolidation_scope", ""),
                    }
                )
    return extracted


def _extract_opra_table_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = Path(str(row.get("local_cache_path") or ""))
    if not path.exists():
        return []
    try:
        tables = pd.read_html(StringIO(path.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        return []

    extracted = []
    emitted: set[Tuple[str, str, str]] = set()
    for table_index, df in enumerate(tables):
        sdf = df.astype(str).fillna("")
        for row_index, series in sdf.iterrows():
            values = [str(x).strip() for x in series.tolist()]
            row_label = next((value for value in values if value and _parse_numeric_cell(value) is None), "")
            if not row_label:
                continue

            normalized_label = _normalize_opra_row_label(row_label)
            classifications = _classify_opra_table_row_label(normalized_label)
            if not classifications:
                continue

            numeric_candidates = []
            for col_index, cell in enumerate(values[1:], start=1):
                parsed = _parse_numeric_cell(cell)
                if parsed is None:
                    continue
                col_label = str(df.columns[col_index]) if col_index < len(df.columns) else ""
                numeric_candidates.append((col_index, parsed, col_label))
            if not numeric_candidates:
                continue

            col_index, parsed_value, col_label = numeric_candidates[0]
            for cls in classifications:
                normalized_field = cls["normalized_field"]
                dedupe_key = (
                    normalized_field,
                    normalized_label.lower(),
                    str(row.get("document_id") or ""),
                )
                if dedupe_key in emitted:
                    continue
                emitted.add(dedupe_key)

                spec = OPRA_TABLE_FIELD_MAP.get(normalized_field, {})
                extracted.append(
                    {
                        "normalized_field": normalized_field,
                        "original_field": row_label,
                        "definition": cls.get("definition", ""),
                        "value": parsed_value,
                        "unit": str(spec.get("expected_unit") or ""),
                        "currency": str(spec.get("expected_currency") or ""),
                        "period": str(row.get("document_date") or "latest"),
                        "period_start": "",
                        "period_end": str(row.get("document_date") or ""),
                        "fiscal_period": str(row.get("document_date") or ""),
                        "instant_or_duration": str(spec.get("period_type") or ""),
                        "source_document_id": str(row.get("document_id") or ""),
                        "source_url": str(row.get("source_url") or ""),
                        "local_cache_path": str(row.get("local_cache_path") or ""),
                        "document_title": str(row.get("document_title") or ""),
                        "table_title": str(row.get("document_title") or row.get("source_type") or ""),
                        "table_index": str(table_index),
                        "row_label": row_label,
                        "normalized_row_label": normalized_label,
                        "column_label": col_label,
                        "page_number": "",
                        "sheet_name": "",
                        "cell_reference": f"table:{table_index};row:{row_index};col:{col_index}",
                        "matched_text": row_label,
                        "extraction_method": "html_table_row_match",
                        "confidence": 90.0,
                        "fact_status": "verified",
                        "consolidation_scope": cls.get("consolidation_scope", ""),
                    }
                )
    return extracted


def _extract_nbis_table_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = Path(str(row.get("local_cache_path") or ""))
    if not path.exists():
        return []
    try:
        tables = pd.read_html(StringIO(path.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        return []

    extracted = []
    emitted: set[Tuple[str, str, str]] = set()
    for table_index, df in enumerate(tables):
        sdf = df.astype(str).fillna("")
        for row_index, series in sdf.iterrows():
            values = [str(x).strip() for x in series.tolist()]
            row_text = _normalize_nbis_row_label(" | ".join(values))
            low = row_text.lower()

            if re.search(r"\bcustomer\s+[a-z0-9]", low):
                numeric_candidates = []
                for col_index, cell in enumerate(values[1:], start=1):
                    parsed = _parse_numeric_cell(cell)
                    if parsed is None:
                        continue
                    col_label = str(df.columns[col_index]) if col_index < len(df.columns) else ""
                    numeric_candidates.append((col_index, parsed, col_label))
                if numeric_candidates:
                    col_index, parsed_value, col_label = numeric_candidates[0]
                    dedupe_key = (
                        "customer_concentration",
                        str(row.get("document_id") or ""),
                        row_text.lower(),
                    )
                    if dedupe_key not in emitted:
                        emitted.add(dedupe_key)
                        spec = NBIS_TABLE_FIELD_MAP["customer_concentration"]
                        extracted.append(
                            {
                                "normalized_field": "customer_concentration",
                                "original_field": row_text,
                                "definition": "major_customer_revenue_share",
                                "value": parsed_value,
                                "unit": str(spec.get("expected_unit") or ""),
                                "currency": str(spec.get("expected_currency") or ""),
                                "period": str(row.get("document_date") or "latest"),
                                "period_start": "",
                                "period_end": str(row.get("document_date") or ""),
                                "fiscal_period": str(row.get("document_date") or ""),
                                "instant_or_duration": str(spec.get("period_type") or ""),
                                "source_document_id": str(row.get("document_id") or ""),
                                "source_url": str(row.get("source_url") or ""),
                                "local_cache_path": str(row.get("local_cache_path") or ""),
                                "document_title": str(row.get("document_title") or ""),
                                "table_title": str(row.get("document_title") or row.get("source_type") or ""),
                                "table_index": str(table_index),
                                "row_label": row_text,
                                "normalized_row_label": row_text,
                                "column_label": col_label,
                                "page_number": "",
                                "sheet_name": "",
                                "cell_reference": f"table:{table_index};row:{row_index};col:{col_index}",
                                "matched_text": row_text,
                                "extraction_method": "html_table_row_match",
                                "confidence": 88.0,
                                "fact_status": "verified",
                                "consolidation_scope": "major_customer",
                            }
                        )

            if "nebius ai cloud business" not in low and "ai infrastructure services" not in low:
                continue

            parsed_value = _extract_nbis_ai_revenue_from_row_text(row_text)
            if parsed_value is None:
                continue

            dedupe_key = (
                "ai_infrastructure_revenue",
                row_text.lower(),
                str(row.get("document_id") or ""),
            )
            if dedupe_key in emitted:
                continue
            emitted.add(dedupe_key)

            spec = NBIS_TABLE_FIELD_MAP["ai_infrastructure_revenue"]
            extracted.append(
                {
                    "normalized_field": "ai_infrastructure_revenue",
                    "original_field": row_text,
                    "definition": "nebius_ai_cloud_revenue",
                    "value": parsed_value,
                    "unit": str(spec.get("expected_unit") or ""),
                    "currency": str(spec.get("expected_currency") or ""),
                    "period": str(row.get("document_date") or "latest"),
                    "period_start": "",
                    "period_end": str(row.get("document_date") or ""),
                    "fiscal_period": str(row.get("document_date") or ""),
                    "instant_or_duration": str(spec.get("period_type") or ""),
                    "source_document_id": str(row.get("document_id") or ""),
                    "source_url": str(row.get("source_url") or ""),
                    "local_cache_path": str(row.get("local_cache_path") or ""),
                    "document_title": str(row.get("document_title") or ""),
                    "table_title": str(row.get("document_title") or row.get("source_type") or ""),
                    "table_index": str(table_index),
                    "row_label": row_text,
                    "normalized_row_label": row_text,
                    "column_label": "",
                    "page_number": "",
                    "sheet_name": "",
                    "cell_reference": f"table:{table_index};row:{row_index}",
                    "matched_text": row_text,
                    "extraction_method": "html_table_row_match",
                    "confidence": 90.0,
                    "fact_status": "verified",
                    "consolidation_scope": "nebius_ai_cloud_segment",
                }
            )
    return extracted


def _normalize_artv_row_label(label: str) -> str:
    text = html.unescape(str(label or "")).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\*\u2020\u2021\u00a7]+$", "", text).strip()
    return text


def _classify_artv_table_row_text(row_text: str) -> List[Dict[str, str]]:
    low = _normalize_artv_row_label(row_text).lower()
    out: List[Dict[str, str]] = []

    if re.search(r"\b(allonk|ab-101|ab-201|ab-205|car-nk)\b", low):
        out.append(
            {
                "normalized_field": "pipeline_programs",
                "definition": "artiva_pipeline_program_reference",
                "consolidation_scope": "clinical_pipeline",
            }
        )

    if re.search(r"\bphase\s*(?:\[)?(?:1/1b|1b|1|2a|2|3)(?:\])?\b", low):
        out.append(
            {
                "normalized_field": "development_stage",
                "definition": "clinical_development_stage_reference",
                "consolidation_scope": "clinical_pipeline",
            }
        )
        out.append(
            {
                "normalized_field": "trial_phase",
                "definition": "clinical_trial_phase_reference",
                "consolidation_scope": "clinical_pipeline",
            }
        )

    if re.search(r"\b(enroll(?:ment|ing)|recruiting\s+approximately)\b", low):
        out.append(
            {
                "normalized_field": "enrollment_status",
                "definition": "clinical_enrollment_status_reference",
                "consolidation_scope": "clinical_pipeline",
            }
        )

    if re.search(r"\b(data\s+(?:readout|cutoff)|expected\s+data)\b", low):
        out.append(
            {
                "normalized_field": "expected_data_readouts",
                "definition": "clinical_data_readout_timeline_reference",
                "consolidation_scope": "clinical_pipeline",
            }
        )

    if re.search(r"\b(fast\s+track|breakthrough|orphan\s+drug\s+designation)\b", low):
        out.append(
            {
                "normalized_field": "regulatory_designations",
                "definition": "regulatory_designation_reference",
                "consolidation_scope": "regulatory",
            }
        )

    if re.search(r"\b(partner|partnership|co-own|collaboration)\b", low):
        out.append(
            {
                "normalized_field": "partnerships",
                "definition": "strategic_partnership_reference",
                "consolidation_scope": "corporate_partnerships",
            }
        )

    if re.search(r"\b(license\s+agreement|royalty-bearing\s+license|licensing\s+agreement)\b", low):
        out.append(
            {
                "normalized_field": "licensing_agreements",
                "definition": "licensing_agreement_reference",
                "consolidation_scope": "corporate_licensing",
            }
        )

    if re.search(r"\b(financing|private\s+placement|offering)\b", low):
        out.append(
            {
                "normalized_field": "recent_financing",
                "definition": "recent_financing_activity_reference",
                "consolidation_scope": "capital_structure",
            }
        )

    if re.search(r"\b(dilution|dilutive)\b", low):
        out.append(
            {
                "normalized_field": "management_stated_dilution_disclosures",
                "definition": "management_dilution_disclosure_reference",
                "consolidation_scope": "capital_structure",
            }
        )

    return out


def _extract_artv_table_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = Path(str(row.get("local_cache_path") or ""))
    if not path.exists():
        return []
    try:
        tables = pd.read_html(StringIO(path.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        return []

    extracted = []
    emitted: set[Tuple[str, str]] = set()
    for table_index, df in enumerate(tables):
        sdf = df.astype(str).fillna("")
        for row_index, series in sdf.iterrows():
            values = [str(x).strip() for x in series.tolist()]
            row_text = _normalize_artv_row_label(" | ".join(values))
            if not row_text:
                continue

            for cls in _classify_artv_table_row_text(row_text):
                normalized_field = cls["normalized_field"]
                dedupe_key = (normalized_field, str(row.get("document_id") or ""))
                if dedupe_key in emitted:
                    continue
                emitted.add(dedupe_key)

                spec = ARTV_TABLE_FIELD_MAP.get(normalized_field, {})
                extracted.append(
                    {
                        "normalized_field": normalized_field,
                        "original_field": row_text,
                        "definition": cls.get("definition", ""),
                        "value": row_text,
                        "unit": str(spec.get("expected_unit") or "text"),
                        "currency": str(spec.get("expected_currency") or ""),
                        "period": str(row.get("document_date") or "latest"),
                        "period_start": "",
                        "period_end": str(row.get("document_date") or ""),
                        "fiscal_period": str(row.get("document_date") or ""),
                        "instant_or_duration": str(spec.get("period_type") or "duration"),
                        "source_document_id": str(row.get("document_id") or ""),
                        "source_url": str(row.get("source_url") or ""),
                        "local_cache_path": str(row.get("local_cache_path") or ""),
                        "document_title": str(row.get("document_title") or ""),
                        "table_title": str(row.get("document_title") or row.get("source_type") or ""),
                        "table_index": str(table_index),
                        "row_label": row_text,
                        "normalized_row_label": row_text,
                        "column_label": "",
                        "page_number": "",
                        "sheet_name": "",
                        "cell_reference": f"table:{table_index};row:{row_index}",
                        "matched_text": row_text,
                        "extraction_method": "html_table_row_match",
                        "confidence": 90.0,
                        "fact_status": "verified",
                        "consolidation_scope": cls.get("consolidation_scope", ""),
                    }
                )
    return extracted


def _write_official_source_registry(tickers: List[str]) -> Dict[str, Any]:
    registry: Dict[str, Any] = {}
    for ticker in tickers:
        entries = []
        for source_type, url in OFFICIAL_SOURCE_URLS.get(ticker, {}).items():
            result = _validate_official_url(url, _expected_identity_terms(ticker))
            result["ticker"] = ticker
            result["source_type"] = source_type
            result["original_url"] = url
            result["final_url"] = result.pop("redirected_url", "")
            result["redirect_chain"] = [url, result["final_url"]] if result["final_url"] and result["final_url"] != url else [url]
            result["document_type_match"] = source_type in {"official_ir_page", "official_bank_regulatory_materials"} or ("fund" in source_type and result.get("issuer_or_sponsor_match"))
            entries.append(result)
        registry[ticker] = entries
    _json_dump(OFFICIAL_SOURCE_REGISTRY_PATH, registry)
    return registry


@dataclass
class Phase1Fact:
    ticker: str
    normalized_field: str
    original_field: str
    taxonomy: str
    value: Any
    unit: str
    period: str
    source_document_id: str
    source_url: str
    source_date: str
    extracted_at: str
    confidence: float
    extraction_method: str
    raw_text_reference: str
    fact_status: str
    source_type: str = ""
    local_cache_path: str = ""
    matched_text: str = ""
    context_before: str = ""
    context_after: str = ""
    source_location: str = ""
    extraction_rule: str = ""
    currency: str = ""
    calculation_metadata: Optional[Dict[str, Any]] = None
    table_title: str = ""
    row_label: str = ""
    column_label: str = ""
    page_number: str = ""
    sheet_name: str = ""
    cell_reference: str = ""
    blocker_reason: str = ""
    definition: str = ""
    period_start: str = ""
    period_end: str = ""
    fiscal_period: str = ""
    instant_or_duration: str = ""
    consolidation_scope: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "field": self.normalized_field,
            "normalized_field": self.normalized_field,
            "original_field": self.original_field,
            "taxonomy": self.taxonomy,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
            "source_document_id": self.source_document_id,
            "source_url": self.source_url,
            "source_date": self.source_date,
            "extracted_at": self.extracted_at,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "raw_text_reference": self.raw_text_reference,
            "fact_status": self.fact_status,
            "source_type": self.source_type,
            "local_cache_path": self.local_cache_path,
            "matched_text": self.matched_text,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "source_location": self.source_location,
            "extraction_rule": self.extraction_rule,
            "currency": self.currency,
            "calculation_metadata": self.calculation_metadata or {},
            "table_title": self.table_title,
            "row_label": self.row_label,
            "column_label": self.column_label,
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "cell_reference": self.cell_reference,
            "blocker_reason": self.blocker_reason,
            "definition": self.definition,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "fiscal_period": self.fiscal_period,
            "instant_or_duration": self.instant_or_duration,
            "consolidation_scope": self.consolidation_scope,
        }


class ResearchCollector:
    """Collect authoritative source documents with local caching and attempt logs."""

    def __init__(self, workspace: Path = WORKSPACE):
        _ensure_dirs()
        self.workspace = workspace
        self.sec = SECDataSource()
        self.finviz = FinvizDataSource()
        self.transcripts = TranscriptDataSource()
        self.collection_index = _json_load(COLLECTION_INDEX_PATH, {})
        if not isinstance(self.collection_index, dict):
            self.collection_index = {}
        self.attempts: List[Dict[str, Any]] = []

    def _save_index(self) -> None:
        _json_dump(COLLECTION_INDEX_PATH, self.collection_index)

    def _record_attempt(
        self,
        ticker: str,
        source_type: str,
        source_name: str,
        source_url: str,
        status: str,
        error: str,
        document_date: str,
        content_hash: str,
        local_cache_path: str,
    ) -> None:
        self.attempts.append(
            {
                "ticker": ticker,
                "source_type": source_type,
                "source_name": source_name,
                "source_url": source_url,
                "attempted_at": _utc_now_iso(),
                "status": status,
                "error": error,
                "document_date": document_date,
                "content_hash": content_hash,
                "local_cache_path": local_cache_path,
            }
        )

    @staticmethod
    def _doc_record(
        ticker: str,
        source_type: str,
        source_name: str,
        document_id: str,
        source_url: str,
        document_date: str,
        local_cache_path: str,
        content_hash: str,
        collection_status: str,
        collection_error: str,
        retrieved_at: str,
    ) -> Dict[str, Any]:
        return {
            "ticker": ticker,
            "source_type": source_type,
            "source_name": source_name,
            "document_id": document_id,
            "source_url": source_url,
            "document_date": document_date,
            "attempted_at": retrieved_at,
            "retrieved_at": retrieved_at,
            "local_cache_path": local_cache_path,
            "content_hash": content_hash,
            "collection_status": collection_status,
            "status": collection_status,
            "collection_error": collection_error,
            "error": collection_error,
        }

    def _cache_doc(self, ticker: str, filename: str, content: bytes) -> Tuple[str, str]:
        ticker_dir = RAW_DIR / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _sanitize_filename(filename)
        out_path = ticker_dir / safe_name
        out_path.write_bytes(content)
        return str(out_path), _stable_hash_bytes(content)

    def _cache_or_reuse(
        self,
        ticker: str,
        source_type: str,
        source_name: str,
        document_id: str,
        source_url: str,
        document_date: str,
        fetch_bytes,
        fallback_filename: str,
    ) -> Dict[str, Any]:
        key = f"{ticker}:{source_type}:{document_id}"
        existing = self.collection_index.get(key)
        attempted_at = _utc_now_iso()

        if isinstance(existing, dict):
            local_path = existing.get("local_cache_path")
            if local_path and Path(local_path).exists():
                row = self._doc_record(
                    ticker=ticker,
                    source_type=source_type,
                    source_name=source_name,
                    document_id=document_id,
                    source_url=source_url,
                    document_date=document_date,
                    local_cache_path=str(local_path),
                    content_hash=str(existing.get("content_hash") or ""),
                    collection_status="cached",
                    collection_error="",
                    retrieved_at=attempted_at,
                )
                self._record_attempt(
                    ticker=ticker,
                    source_type=source_type,
                    source_name=source_name,
                    source_url=source_url,
                    status="cached",
                    error="",
                    document_date=document_date,
                    content_hash=row["content_hash"],
                    local_cache_path=row["local_cache_path"],
                )
                return row

        try:
            payload = fetch_bytes()
            if payload is None:
                row = self._doc_record(
                    ticker=ticker,
                    source_type=source_type,
                    source_name=source_name,
                    document_id=document_id,
                    source_url=source_url,
                    document_date=document_date,
                    local_cache_path="",
                    content_hash="",
                    collection_status="missing",
                    collection_error="no payload returned",
                    retrieved_at=attempted_at,
                )
                self._record_attempt(
                    ticker=ticker,
                    source_type=source_type,
                    source_name=source_name,
                    source_url=source_url,
                    status="missing",
                    error="no payload returned",
                    document_date=document_date,
                    content_hash="",
                    local_cache_path="",
                )
                return row

            path_text, digest = self._cache_doc(
                ticker=ticker,
                filename=fallback_filename,
                content=payload,
            )
            row = self._doc_record(
                ticker=ticker,
                source_type=source_type,
                source_name=source_name,
                document_id=document_id,
                source_url=source_url,
                document_date=document_date,
                local_cache_path=path_text,
                content_hash=digest,
                collection_status="retrieved",
                collection_error="",
                retrieved_at=attempted_at,
            )
            self.collection_index[key] = row
            self._save_index()
            self._record_attempt(
                ticker=ticker,
                source_type=source_type,
                source_name=source_name,
                source_url=source_url,
                status="retrieved",
                error="",
                document_date=document_date,
                content_hash=digest,
                local_cache_path=path_text,
            )
            return row
        except Exception as exc:
            err = str(exc)
            row = self._doc_record(
                ticker=ticker,
                source_type=source_type,
                source_name=source_name,
                document_id=document_id,
                source_url=source_url,
                document_date=document_date,
                local_cache_path="",
                content_hash="",
                collection_status="error",
                collection_error=err,
                retrieved_at=attempted_at,
            )
            self._record_attempt(
                ticker=ticker,
                source_type=source_type,
                source_name=source_name,
                source_url=source_url,
                status="error",
                error=err,
                document_date=document_date,
                content_hash="",
                local_cache_path="",
            )
            return row

    def _fetch_text_bytes(self, url: str) -> Optional[bytes]:
        if "sec.gov" in str(url):
            resp = self.sec.session.get(url, timeout=30)
        else:
            resp = requests.get(url, timeout=12, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return resp.text.encode("utf-8", errors="ignore")

    def _fetch_json_bytes(self, url: str) -> Optional[bytes]:
        resp = self.sec.session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return (json.dumps(data, indent=2) + "\n").encode("utf-8")

    @staticmethod
    def _latest_filing(recent: Dict[str, Any], preferred_forms: Iterable[str], keyword_hints: Iterable[str]) -> Optional[Dict[str, str]]:
        forms = recent.get("form") or []
        filing_dates = recent.get("filingDate") or []
        accession = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []

        preferred = {str(x).upper() for x in preferred_forms}
        hints = [str(x).lower() for x in keyword_hints]

        for i in range(min(len(forms), len(filing_dates), len(accession), len(primary_docs))):
            form = str(forms[i] or "").upper()
            if form not in preferred:
                continue
            primary = str(primary_docs[i] or "")
            low = primary.lower()
            if hints and not any(h in low for h in hints):
                continue
            return {
                "form": form,
                "filing_date": str(filing_dates[i] or ""),
                "accession": str(accession[i] or ""),
                "primary_document": primary,
            }

        for i in range(min(len(forms), len(filing_dates), len(accession), len(primary_docs))):
            form = str(forms[i] or "").upper()
            if form in preferred:
                return {
                    "form": form,
                    "filing_date": str(filing_dates[i] or ""),
                    "accession": str(accession[i] or ""),
                    "primary_document": str(primary_docs[i] or ""),
                }
        return None

    def _collect_official_urls(self, ticker: str, documents: List[Dict[str, Any]]) -> None:
        source_map = OFFICIAL_SOURCE_URLS.get(ticker, {})
        for source_type, source_url in source_map.items():
            doc = self._cache_or_reuse(
                ticker=ticker,
                source_type=source_type,
                source_name="Official Source",
                document_id=source_type,
                source_url=source_url,
                document_date="",
                fetch_bytes=lambda u=source_url: self._fetch_text_bytes(u),
                fallback_filename=f"{source_type}.html",
            )
            documents.append(doc)

    def _placeholder_missing(
        self,
        ticker: str,
        source_type: str,
        source_name: str,
        collection_error: str,
    ) -> Dict[str, Any]:
        row = self._doc_record(
            ticker=ticker,
            source_type=source_type,
            source_name=source_name,
            document_id="",
            source_url="",
            document_date="",
            local_cache_path="",
            content_hash="",
            collection_status="missing",
            collection_error=collection_error,
            retrieved_at=_utc_now_iso(),
        )
        self._record_attempt(
            ticker=ticker,
            source_type=source_type,
            source_name=source_name,
            source_url="",
            status="missing",
            error=collection_error,
            document_date="",
            content_hash="",
            local_cache_path="",
        )
        return row

    def _collect_vbnk_discovered_documents(self, ticker: str, documents: List[Dict[str, Any]]) -> None:
        parents = [d for d in documents if d.get("source_type") in {"latest_annual_filing", "latest_quarterly_filing", "official_bank_regulatory_materials"} and d.get("local_cache_path")]
        seen_urls = {str(d.get("source_url") or "") for d in documents}
        for parent in parents:
            for link in _discover_vbnk_exhibit_links(parent):
                final_url = str(link.get("final_url") or "")
                if not final_url or final_url in seen_urls:
                    continue
                source_type = f"vbnk_{link.get('document_type') or 'document'}"
                doc_id = _sanitize_filename(Path(final_url).name)
                row = self._cache_or_reuse(
                    ticker=ticker,
                    source_type=source_type,
                    source_name="VBNK Discovered Official Document",
                    document_id=doc_id,
                    source_url=final_url,
                    document_date=str(parent.get("document_date") or ""),
                    fetch_bytes=lambda u=final_url: self._fetch_text_bytes(u),
                    fallback_filename=doc_id,
                )
                row["source_page_url"] = str(link.get("source_page_url") or "")
                row["document_title"] = str(link.get("document_title") or "")
                row["document_type"] = str(link.get("document_type") or "")
                row["reporting_period"] = str(parent.get("document_date") or "")
                row["currency"] = "CAD"
                row["issuer_match"] = True
                row["document_type_match"] = row.get("collection_status") in {"retrieved", "cached"}
                documents.append(row)
                seen_urls.add(final_url)

    def collect_ticker(self, ticker: str, security_type: str) -> Dict[str, Any]:
        ticker = ticker.upper().strip()
        self.attempts = []
        collected_at = _utc_now_iso()
        documents: List[Dict[str, Any]] = []

        cik = self.sec.get_cik_for_ticker(ticker)
        if not cik:
            documents.append(
                self._placeholder_missing(
                    ticker=ticker,
                    source_type="sec_cik_lookup",
                    source_name="SEC EDGAR",
                    collection_error="CIK not found",
                )
            )
            package = {
                "ticker": ticker,
                "security_type": security_type,
                "collected_at": collected_at,
                "documents": documents,
            }
            _json_dump(RAW_DIR / ticker / "phase1_collection.json", package)
            _json_dump(LOGS_DIR / f"{ticker}_source_attempts.json", {"ticker": ticker, "attempts": self.attempts})
            return package

        cik_stripped = str(int(str(cik)))
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        companyfacts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

        documents.append(
            self._cache_or_reuse(
                ticker=ticker,
                source_type="sec_submissions",
                source_name="SEC EDGAR",
                document_id=f"CIK{cik}:submissions",
                source_url=submissions_url,
                document_date="",
                fetch_bytes=lambda: self._fetch_json_bytes(submissions_url),
                fallback_filename="sec_submissions.json",
            )
        )
        documents.append(
            self._cache_or_reuse(
                ticker=ticker,
                source_type="sec_companyfacts",
                source_name="SEC EDGAR",
                document_id=f"CIK{cik}:companyfacts",
                source_url=companyfacts_url,
                document_date="",
                fetch_bytes=lambda: self._fetch_json_bytes(companyfacts_url),
                fallback_filename="sec_companyfacts.json",
            )
        )

        submissions_payload = {}
        if documents[0].get("local_cache_path"):
            submissions_payload = _json_load(Path(documents[0]["local_cache_path"]), {})
        recent = ((submissions_payload or {}).get("filings") or {}).get("recent") or {}

        annual_forms = ["10-K", "20-F", "40-F"]
        quarterly_forms = ["10-Q", "6-K"]
        release_forms = ["8-K", "6-K"]
        if security_type == "etf_fund":
            annual_forms = ["N-CSR", "N-CSRS", "485BPOS", "497", "S-1", "S-1/A", "N-1A"]
            quarterly_forms = ["NPORT-P", "N-Q", "6-K", "8-K"]
            release_forms = ["497", "8-K", "NPORT-P", "S-1", "S-1/A"]

        latest_annual = self._latest_filing(recent, annual_forms, keyword_hints=["annual", "report", "20f", "40f"])
        latest_quarterly = self._latest_filing(recent, quarterly_forms, keyword_hints=["quarter", "interim", "6k", "10q", "nport"])
        latest_release = self._latest_filing(recent, release_forms, keyword_hints=["earn", "result", "release", "press", "factsheet"])
        latest_presentation = self._latest_filing(recent, release_forms, keyword_hints=["presentation", "slides", "deck"])
        latest_guidance = self._latest_filing(recent, release_forms, keyword_hints=["guidance", "outlook"])

        def filing_to_url(row: Dict[str, str]) -> Tuple[str, str]:
            accession = str(row.get("accession") or "")
            doc = str(row.get("primary_document") or "")
            filing_date = str(row.get("filing_date") or "")
            if not accession or not doc:
                return "", filing_date
            acc_clean = accession.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_clean}/{doc}"
            return url, filing_date

        for role, filing in [
            ("latest_annual_filing", latest_annual),
            ("latest_quarterly_filing", latest_quarterly),
            ("latest_earnings_release", latest_release),
            ("latest_investor_presentation", latest_presentation),
            ("latest_guidance", latest_guidance),
        ]:
            if not filing:
                documents.append(
                    self._placeholder_missing(
                        ticker=ticker,
                        source_type=role,
                        source_name="SEC EDGAR",
                        collection_error="No matching filing found",
                    )
                )
                continue
            source_url, filing_date = filing_to_url(filing)
            accession = str(filing.get("accession") or "")
            form = str(filing.get("form") or "")
            doc_id = f"{form}:{accession}"
            documents.append(
                self._cache_or_reuse(
                    ticker=ticker,
                    source_type=role,
                    source_name="SEC EDGAR",
                    document_id=doc_id,
                    source_url=source_url,
                    document_date=filing_date,
                    fetch_bytes=lambda u=source_url: self._fetch_text_bytes(u),
                    fallback_filename=f"{role}_{_sanitize_filename(doc_id)}.txt",
                )
            )

        transcript_payload = self.transcripts.fetch_symbol(ticker)
        transcript_urls = list(transcript_payload.get("source_urls") or [])
        if transcript_urls:
            for i, url in enumerate(transcript_urls, 1):
                documents.append(
                    self._cache_or_reuse(
                        ticker=ticker,
                        source_type="earnings_call_transcript",
                        source_name="SEC Official Earnings Materials",
                        document_id=f"transcript_material_{i}",
                        source_url=url,
                        document_date="",
                        fetch_bytes=lambda u=url: self._fetch_text_bytes(u),
                        fallback_filename=f"earnings_call_material_{i}.txt",
                    )
                )
        else:
            if ticker in {"OPRA", "NBIS"}:
                fallback_rows = [d for d in documents if d.get("source_type") in {"latest_earnings_release", "latest_quarterly_filing"} and d.get("source_url")]
                for i, base_row in enumerate(fallback_rows, 1):
                    fallback_url = str(base_row.get("source_url") or "")
                    documents.append(
                        self._cache_or_reuse(
                            ticker=ticker,
                            source_type="earnings_call_transcript",
                            source_name="SEC Official Earnings Materials",
                            document_id=f"{ticker.lower()}_transcript_fallback_{i}",
                            source_url=fallback_url,
                            document_date=str(base_row.get("document_date") or ""),
                            fetch_bytes=lambda u=fallback_url: self._fetch_text_bytes(u),
                            fallback_filename=f"{ticker.lower()}_earnings_call_fallback_{i}.txt",
                        )
                    )
                if not fallback_rows:
                    documents.append(
                        self._placeholder_missing(
                            ticker=ticker,
                            source_type="earnings_call_transcript",
                            source_name="SEC Official Earnings Materials",
                            collection_error="No legally accessible transcript material found",
                        )
                    )
            else:
                documents.append(
                    self._placeholder_missing(
                        ticker=ticker,
                        source_type="earnings_call_transcript",
                        source_name="SEC Official Earnings Materials",
                        collection_error="No legally accessible transcript material found",
                    )
                )

        self._collect_official_urls(ticker, documents)

        if ticker == "VBNK":
            self._collect_vbnk_discovered_documents(ticker, documents)

        market_snapshot = None
        market_error = ""
        try:
            market_snapshot = self.finviz._fetch_snapshot(ticker)
        except Exception as exc:
            market_error = str(exc)

        if market_snapshot:
            payload_bytes = (json.dumps(market_snapshot, indent=2) + "\n").encode("utf-8")
            path_text, digest = self._cache_doc(ticker=ticker, filename="finviz_snapshot.json", content=payload_bytes)
            row = self._doc_record(
                ticker=ticker,
                source_type="market_data",
                source_name="Finviz",
                document_id="finviz_snapshot",
                source_url=f"https://finviz.com/quote.ashx?t={ticker}",
                document_date="",
                local_cache_path=path_text,
                content_hash=digest,
                collection_status="retrieved",
                collection_error="",
                retrieved_at=_utc_now_iso(),
            )
            documents.append(row)
            self.collection_index[f"{ticker}:market_data:finviz_snapshot"] = row
            self._save_index()
            self._record_attempt(
                ticker=ticker,
                source_type="market_data",
                source_name="Finviz",
                source_url=row["source_url"],
                status="retrieved",
                error="",
                document_date="",
                content_hash=digest,
                local_cache_path=path_text,
            )
        else:
            row = self._doc_record(
                ticker=ticker,
                source_type="market_data",
                source_name="Finviz",
                document_id="finviz_snapshot",
                source_url=f"https://finviz.com/quote.ashx?t={ticker}",
                document_date="",
                local_cache_path="",
                content_hash="",
                collection_status="error" if market_error else "missing",
                collection_error=market_error or "No market snapshot returned",
                retrieved_at=_utc_now_iso(),
            )
            documents.append(row)
            self._record_attempt(
                ticker=ticker,
                source_type="market_data",
                source_name="Finviz",
                source_url=row["source_url"],
                status=row["collection_status"],
                error=row["collection_error"],
                document_date="",
                content_hash="",
                local_cache_path="",
            )

        seen = set()
        deduped_docs = []
        for row in documents:
            key = (row.get("source_type"), row.get("document_id"), row.get("source_url"))
            if key in seen:
                continue
            seen.add(key)
            deduped_docs.append(row)

        package = {
            "ticker": ticker,
            "security_type": security_type,
            "collected_at": collected_at,
            "documents": deduped_docs,
        }
        _json_dump(RAW_DIR / ticker / "phase1_collection.json", package)
        _json_dump(LOGS_DIR / f"{ticker}_source_attempts.json", {"ticker": ticker, "attempts": self.attempts})
        return package


class ResearchParser:
    """Convert collected source documents into normalized facts."""

    def __init__(self):
        self.sec = SECDataSource()

    def _extract_latest_companyfact(
        self,
        companyfacts: Dict[str, Any],
        aliases_by_taxonomy: Dict[str, List[str]],
        preferred_units: Optional[List[str]] = None,
    ) -> Tuple[Any, str, str, str, str, str, str]:
        preferred = preferred_units or ["USD"]
        facts = companyfacts.get("facts") or {}

        best = None
        for taxonomy, aliases in aliases_by_taxonomy.items():
            tax_data = facts.get(taxonomy) or {}
            for alias in aliases:
                concept_data = tax_data.get(alias) or {}
                units = concept_data.get("units") or {}
                rows = self.sec._select_unit_data(units, preferred)
                default_unit_name = next(iter(units.keys()), "")
                for row in rows:
                    val = row.get("val")
                    end = str(row.get("end") or "")
                    filed = str(row.get("filed") or "")
                    form = str(row.get("form") or "")
                    unit = str(row.get("uom") or default_unit_name or "")
                    if val is None or not end:
                        continue
                    item = (end, filed, val, taxonomy, alias, unit, form)
                    if best is None or (item[0], item[1]) > (best[0], best[1]):
                        best = item

        if best is None:
            return None, "", "", "", "", "", ""
        end, filed, val, taxonomy, alias, unit, form = best
        return val, end, filed, taxonomy, alias, unit, f"{taxonomy}:{alias}:{form}:{end}" if form else f"{taxonomy}:{alias}:{end}"

    def _extract_series(
        self,
        companyfacts: Dict[str, Any],
        aliases_by_taxonomy: Dict[str, List[str]],
        preferred_units: Optional[List[str]] = None,
    ) -> List[Tuple[str, str, float]]:
        preferred = preferred_units or ["USD"]
        facts = companyfacts.get("facts") or {}
        out: List[Tuple[str, str, float]] = []
        for taxonomy, aliases in aliases_by_taxonomy.items():
            tax_data = facts.get(taxonomy) or {}
            for alias in aliases:
                concept_data = tax_data.get(alias) or {}
                units = concept_data.get("units") or {}
                rows = self.sec._select_unit_data(units, preferred)
                for row in rows:
                    val = row.get("val")
                    end = str(row.get("end") or "")
                    filed = str(row.get("filed") or "")
                    if val is None or not end:
                        continue
                    try:
                        out.append((end, filed, float(val)))
                    except (TypeError, ValueError):
                        continue
        out.sort()
        return out

    def _extract_from_finviz(self, collection_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        for row in collection_docs:
            if row.get("source_type") != "market_data":
                continue
            cache_path = row.get("local_cache_path")
            if not cache_path:
                continue
            payload = _json_load(Path(cache_path), {})
            if isinstance(payload, dict) and payload:
                return payload
        return {}

    def _load_doc_text(self, row: Dict[str, Any]) -> str:
        path = row.get("local_cache_path")
        if not path:
            return ""
        p = Path(path)
        if not p.exists():
            return ""
        raw = p.read_text(encoding="utf-8", errors="ignore")
        return _clean_text(raw)

    def _capture_text_match(self, text: str, pattern: str, percent: bool = False, string_only: bool = False) -> Optional[Dict[str, Any]]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        start, end = match.span(0)
        matched_text = match.group(0)[:240]
        before = text[max(0, start - 140):start].strip()
        after = text[end:min(len(text), end + 140)].strip()
        line_no = text.count("\n", 0, start) + 1
        value = None
        if string_only:
            value = matched_text
        else:
            raw = match.group(1)
            if percent:
                try:
                    value = float(str(raw).replace("%", "").replace(",", ""))
                except ValueError:
                    value = None
            else:
                value = _parse_human_number(raw)
        return {
            "value": value,
            "matched_text": matched_text,
            "context_before": before,
            "context_after": after,
            "source_location": f"line:{line_no};char:{start}",
            "extraction_rule": pattern,
        }

    def _extract_text_matches(
        self,
        rows: List[Dict[str, Any]],
        patterns: List[str],
        percent: bool = False,
        string_only: bool = False,
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for row in rows:
            text = self._load_doc_text(row)
            if not text:
                continue
            for pattern in patterns:
                captured = self._capture_text_match(text, pattern, percent=percent, string_only=string_only)
                if not captured:
                    continue
                captured.update(
                    {
                        "source_document_id": str(row.get("document_id") or ""),
                        "source_url": str(row.get("source_url") or ""),
                        "source_date": str(row.get("document_date") or ""),
                        "source_type": str(row.get("source_type") or ""),
                        "local_cache_path": str(row.get("local_cache_path") or ""),
                    }
                )
                matches.append(captured)
                break
        return matches

    def parse_ticker(self, collection: Dict[str, Any]) -> Dict[str, Any]:
        ticker = str(collection.get("ticker", "")).upper()
        security_type = str(collection.get("security_type", "operating_company"))
        docs = list(collection.get("documents") or [])
        source_by_type = {str(d.get("source_type")): d for d in docs if isinstance(d, dict)}

        companyfacts_doc = source_by_type.get("sec_companyfacts")
        companyfacts = {}
        if companyfacts_doc and companyfacts_doc.get("local_cache_path"):
            companyfacts = _json_load(Path(companyfacts_doc["local_cache_path"]), {})

        facts: List[Phase1Fact] = []

        def add_fact(
            normalized_field: str,
            value: Any,
            unit: str,
            period: str,
            source_document_id: str,
            source_url: str,
            source_date: str,
            confidence: float,
            extraction_method: str,
            raw_text_reference: str,
            fact_status: str,
            original_field: str = "",
            taxonomy: str = "",
            source_type: str = "",
            local_cache_path: str = "",
            matched_text: str = "",
            context_before: str = "",
            context_after: str = "",
            source_location: str = "",
            extraction_rule: str = "",
            currency: str = "",
            calculation_metadata: Optional[Dict[str, Any]] = None,
            table_title: str = "",
            row_label: str = "",
            column_label: str = "",
            page_number: str = "",
            sheet_name: str = "",
            cell_reference: str = "",
            blocker_reason: str = "",
            definition: str = "",
            period_start: str = "",
            period_end: str = "",
            fiscal_period: str = "",
            instant_or_duration: str = "",
            consolidation_scope: str = "",
        ) -> None:
            facts.append(
                Phase1Fact(
                    ticker=ticker,
                    normalized_field=normalized_field,
                    original_field=original_field or normalized_field,
                    taxonomy=taxonomy or "derived",
                    value=value,
                    unit=unit,
                    period=period,
                    source_document_id=source_document_id,
                    source_url=source_url,
                    source_date=source_date,
                    extracted_at=_utc_now_iso(),
                    confidence=confidence,
                    extraction_method=extraction_method,
                    raw_text_reference=raw_text_reference,
                    fact_status=fact_status,
                    source_type=source_type,
                    local_cache_path=local_cache_path,
                    matched_text=matched_text,
                    context_before=context_before,
                    context_after=context_after,
                    source_location=source_location,
                    extraction_rule=extraction_rule,
                    currency=currency,
                    calculation_metadata=calculation_metadata,
                    table_title=table_title,
                    row_label=row_label,
                    column_label=column_label,
                    page_number=page_number,
                    sheet_name=sheet_name,
                    cell_reference=cell_reference,
                    blocker_reason=blocker_reason,
                    definition=definition,
                    period_start=period_start,
                    period_end=period_end,
                    fiscal_period=fiscal_period,
                    instant_or_duration=instant_or_duration,
                    consolidation_scope=consolidation_scope,
                )
            )

        # XBRL extraction with taxonomy aliases.
        for normalized_field, spec in XBRL_FIELD_MAPPINGS.items():
            aliases = spec.get("aliases") or {}
            units = spec.get("units") or ["USD"]
            value, period, filed, taxonomy, original_field, actual_unit, ref = self._extract_latest_companyfact(companyfacts, aliases, units)
            src = companyfacts_doc or {}
            fact_unit = actual_unit or (units[0] if units else "")
            currency = _infer_currency(fact_unit)
            if value is None:
                add_fact(
                    normalized_field=normalized_field,
                    value=None,
                    unit=fact_unit,
                    period=period or "latest",
                    source_document_id=str(src.get("document_id") or ""),
                    source_url=str(src.get("source_url") or ""),
                    source_date=filed or str(src.get("document_date") or ""),
                    confidence=0.0,
                    extraction_method="xbrl_concept_latest",
                    raw_text_reference=ref,
                    fact_status="missing",
                    original_field=original_field,
                    taxonomy=taxonomy,
                    source_type=str(src.get("source_type") or ""),
                    local_cache_path=str(src.get("local_cache_path") or ""),
                    currency=currency,
                )
            else:
                add_fact(
                    normalized_field=normalized_field,
                    value=value,
                    unit=fact_unit,
                    period=period or "latest",
                    source_document_id=str(src.get("document_id") or ""),
                    source_url=str(src.get("source_url") or ""),
                    source_date=filed or str(src.get("document_date") or ""),
                    confidence=95.0,
                    extraction_method="xbrl_concept_latest",
                    raw_text_reference=ref,
                    fact_status="verified",
                    original_field=original_field,
                    taxonomy=taxonomy,
                    source_type=str(src.get("source_type") or ""),
                    local_cache_path=str(src.get("local_cache_path") or ""),
                    currency=currency,
                )

        # Derived factual metrics.
        by_field = {}
        for f in facts:
            if f.fact_status == "verified":
                by_field[f.normalized_field] = f

        if "cash" in by_field and "debt" in by_field and by_field["cash"].currency == by_field["debt"].currency:
            add_fact(
                normalized_field="net_cash",
                value=float(by_field["cash"].value) - float(by_field["debt"].value),
            unit=by_field["cash"].unit,
            period=by_field["cash"].period,
                source_document_id=by_field["cash"].source_document_id,
                source_url=by_field["cash"].source_url,
                source_date=by_field["cash"].source_date,
                confidence=90.0,
                extraction_method="derived_from_verified_facts",
                raw_text_reference="net_cash=cash-debt",
                fact_status="verified",
                original_field="net_cash",
                taxonomy="derived",
                source_type=by_field["cash"].source_type,
                local_cache_path=by_field["cash"].local_cache_path,
                currency=by_field["cash"].currency,
                calculation_metadata={
                    "formula": "net_cash = cash - debt",
                    "inputs": ["cash", "debt"],
                    "input_periods": [by_field["cash"].period, by_field["debt"].period],
                    "input_currencies": [by_field["cash"].currency, by_field["debt"].currency],
                    "calculation_timestamp": _utc_now_iso(),
                },
            )

        if "gross_profit" in by_field and "revenue" in by_field and float(by_field["revenue"].value or 0) != 0 and by_field["gross_profit"].period == by_field["revenue"].period and by_field["gross_profit"].currency == by_field["revenue"].currency:
            add_fact(
                normalized_field="gross_margin",
                value=(float(by_field["gross_profit"].value) / float(by_field["revenue"].value)) * 100.0,
                unit="percent",
                period=by_field["revenue"].period,
                source_document_id=by_field["gross_profit"].source_document_id,
                source_url=by_field["gross_profit"].source_url,
                source_date=by_field["gross_profit"].source_date,
                confidence=90.0,
                extraction_method="derived_from_verified_facts",
                raw_text_reference="gross_margin=gross_profit/revenue",
                fact_status="verified",
                original_field="gross_margin",
                taxonomy="derived",
                source_type=by_field["gross_profit"].source_type,
                local_cache_path=by_field["gross_profit"].local_cache_path,
                calculation_metadata={
                    "formula": "gross_margin = gross_profit / revenue",
                    "inputs": ["gross_profit", "revenue"],
                    "input_periods": [by_field["gross_profit"].period, by_field["revenue"].period],
                    "input_currencies": [by_field["gross_profit"].currency, by_field["revenue"].currency],
                    "requires_same_period": True,
                    "calculation_timestamp": _utc_now_iso(),
                },
            )

        if ticker == "NBIS" and "gross_margin" not in by_field and "revenue" in by_field:
            cost_val, cost_period, cost_filed, cost_taxonomy, cost_alias, _, _ = self._extract_latest_companyfact(
                companyfacts,
                {"us-gaap": ["CostOfRevenue"]},
                ["USD"],
            )
            if cost_val is not None and float(by_field["revenue"].value or 0) != 0 and cost_period == by_field["revenue"].period:
                gross_profit_value = float(by_field["revenue"].value) - float(cost_val)
                add_fact(
                    normalized_field="gross_margin",
                    value=(gross_profit_value / float(by_field["revenue"].value)) * 100.0,
                    unit="percent",
                    period=by_field["revenue"].period,
                    source_document_id=by_field["revenue"].source_document_id,
                    source_url=by_field["revenue"].source_url,
                    source_date=cost_filed or by_field["revenue"].source_date,
                    confidence=86.0,
                    extraction_method="derived_from_companyfacts_series",
                    raw_text_reference="gross_margin=(revenue-cost_of_revenue)/revenue",
                    fact_status="verified",
                    original_field="gross_margin",
                    taxonomy="derived",
                    source_type=by_field["revenue"].source_type,
                    local_cache_path=by_field["revenue"].local_cache_path,
                    currency=by_field["revenue"].currency,
                    definition="gross_margin_from_cost_of_revenue",
                    calculation_metadata={
                        "formula": "gross_margin = (revenue - cost_of_revenue) / revenue",
                        "inputs": ["revenue", "cost_of_revenue"],
                        "input_values": [by_field["revenue"].value, cost_val],
                        "input_periods": [by_field["revenue"].period, cost_period],
                        "input_currencies": [by_field["revenue"].currency, by_field["revenue"].currency],
                        "companyfacts_concept": f"{cost_taxonomy}:{cost_alias}",
                        "calculation_timestamp": _utc_now_iso(),
                    },
                )

        if "operating_income" in by_field and "revenue" in by_field and float(by_field["revenue"].value or 0) != 0 and by_field["operating_income"].period == by_field["revenue"].period and by_field["operating_income"].currency == by_field["revenue"].currency:
            add_fact(
                normalized_field="operating_margin",
                value=(float(by_field["operating_income"].value) / float(by_field["revenue"].value)) * 100.0,
                unit="percent",
                period=by_field["revenue"].period,
                source_document_id=by_field["operating_income"].source_document_id,
                source_url=by_field["operating_income"].source_url,
                source_date=by_field["operating_income"].source_date,
                confidence=90.0,
                extraction_method="derived_from_verified_facts",
                raw_text_reference="operating_margin=operating_income/revenue",
                fact_status="verified",
                original_field="operating_margin",
                taxonomy="derived",
                source_type=by_field["operating_income"].source_type,
                local_cache_path=by_field["operating_income"].local_cache_path,
                calculation_metadata={
                    "formula": "operating_margin = operating_income / revenue",
                    "inputs": ["operating_income", "revenue"],
                    "input_periods": [by_field["operating_income"].period, by_field["revenue"].period],
                    "input_currencies": [by_field["operating_income"].currency, by_field["revenue"].currency],
                    "requires_same_period": True,
                    "calculation_timestamp": _utc_now_iso(),
                },
            )

        if "free_cash_flow" in by_field and "revenue" in by_field and float(by_field["revenue"].value or 0) != 0 and by_field["free_cash_flow"].period == by_field["revenue"].period and by_field["free_cash_flow"].currency == by_field["revenue"].currency:
            add_fact(
                normalized_field="free_cash_flow_margin",
                value=(float(by_field["free_cash_flow"].value) / float(by_field["revenue"].value)) * 100.0,
                unit="percent",
                period=by_field["revenue"].period,
                source_document_id=by_field["free_cash_flow"].source_document_id,
                source_url=by_field["free_cash_flow"].source_url,
                source_date=by_field["free_cash_flow"].source_date,
                confidence=90.0,
                extraction_method="derived_from_verified_facts",
                raw_text_reference="free_cash_flow_margin=free_cash_flow/revenue",
                fact_status="verified",
                original_field="free_cash_flow_margin",
                taxonomy="derived",
                source_type=by_field["free_cash_flow"].source_type,
                local_cache_path=by_field["free_cash_flow"].local_cache_path,
                calculation_metadata={
                    "formula": "free_cash_flow_margin = free_cash_flow / revenue",
                    "inputs": ["free_cash_flow", "revenue"],
                    "input_periods": [by_field["free_cash_flow"].period, by_field["revenue"].period],
                    "input_currencies": [by_field["free_cash_flow"].currency, by_field["revenue"].currency],
                    "requires_same_period": True,
                    "calculation_timestamp": _utc_now_iso(),
                },
            )

        # Growth and dilution from historical series.
        revenue_series = self._extract_series(companyfacts, XBRL_FIELD_MAPPINGS["revenue"]["aliases"], ["USD"])
        if len(revenue_series) >= 2 and revenue_series[-2][2] != 0:
            growth = ((revenue_series[-1][2] - revenue_series[-2][2]) / abs(revenue_series[-2][2])) * 100.0
            add_fact(
                normalized_field="revenue_growth",
                value=growth,
                unit="percent",
                period=revenue_series[-1][0],
                source_document_id=str(companyfacts_doc.get("document_id") if companyfacts_doc else ""),
                source_url=str(companyfacts_doc.get("source_url") if companyfacts_doc else ""),
                source_date=revenue_series[-1][1],
                confidence=88.0,
                extraction_method="derived_from_companyfacts_series",
                raw_text_reference="revenue_growth=(latest-prev)/prev",
                fact_status="verified",
                original_field="revenue_growth",
                taxonomy="derived",
                source_type=str(companyfacts_doc.get("source_type") if companyfacts_doc else ""),
                local_cache_path=str(companyfacts_doc.get("local_cache_path") if companyfacts_doc else ""),
                calculation_metadata={
                    "formula": "revenue_growth = (latest - previous) / previous",
                    "inputs": ["revenue_series_latest", "revenue_series_previous"],
                    "input_periods": [revenue_series[-1][0], revenue_series[-2][0]],
                    "calculation_timestamp": _utc_now_iso(),
                },
            )

        share_series = self._extract_series(companyfacts, XBRL_FIELD_MAPPINGS["share_count"]["aliases"], ["shares"])
        if len(share_series) >= 2 and share_series[-2][2] != 0:
            chg = ((share_series[-1][2] - share_series[-2][2]) / abs(share_series[-2][2])) * 100.0
            add_fact(
                normalized_field="share_count_change",
                value=chg,
                unit="percent",
                period=share_series[-1][0],
                source_document_id=str(companyfacts_doc.get("document_id") if companyfacts_doc else ""),
                source_url=str(companyfacts_doc.get("source_url") if companyfacts_doc else ""),
                source_date=share_series[-1][1],
                confidence=88.0,
                extraction_method="derived_from_companyfacts_series",
                raw_text_reference="share_count_change=(latest-prev)/prev",
                fact_status="verified",
                original_field="share_count_change",
                taxonomy="derived",
                source_type=str(companyfacts_doc.get("source_type") if companyfacts_doc else ""),
                local_cache_path=str(companyfacts_doc.get("local_cache_path") if companyfacts_doc else ""),
                calculation_metadata={
                    "formula": "share_count_change = (latest - previous) / previous",
                    "inputs": ["share_count_latest", "share_count_previous"],
                    "input_periods": [share_series[-1][0], share_series[-2][0]],
                    "calculation_timestamp": _utc_now_iso(),
                },
            )

        # Text-based extraction from official documents.
        text_source_types = {
            "latest_annual_filing",
            "latest_quarterly_filing",
            "latest_earnings_release",
            "latest_investor_presentation",
            "latest_guidance",
            "official_ir_page",
            "official_bank_regulatory_materials",
            "official_pipeline_page",
            "official_fund_sponsor_page",
            "official_etf_fact_sheet",
            "official_fund_holdings",
        }
        text_rows = [d for d in docs if d.get("source_type") in text_source_types and d.get("local_cache_path")]

        if ticker == "VBNK":
            for row in docs:
                if not str(row.get("source_type") or "").startswith("vbnk_"):
                    continue
                for table_fact in _extract_vbnk_table_rows(row):
                    add_fact(
                        normalized_field=str(table_fact.get("normalized_field") or ""),
                        value=table_fact.get("value"),
                        unit=str(table_fact.get("unit") or ""),
                        period=str(table_fact.get("period") or "latest"),
                        source_document_id=str(table_fact.get("source_document_id") or ""),
                        source_url=str(table_fact.get("source_url") or ""),
                        source_date=str(row.get("document_date") or ""),
                        confidence=float(table_fact.get("confidence") or 0.0),
                        extraction_method=str(table_fact.get("extraction_method") or "html_table_row_match"),
                        raw_text_reference=str(table_fact.get("matched_text") or ""),
                        fact_status=str(table_fact.get("fact_status") or "verified"),
                        original_field=str(table_fact.get("row_label") or table_fact.get("normalized_field") or ""),
                        taxonomy="table",
                        source_type="vbnk_table",
                        local_cache_path=str(table_fact.get("local_cache_path") or ""),
                        matched_text=str(table_fact.get("matched_text") or ""),
                        row_label=str(table_fact.get("row_label") or ""),
                        column_label=str(table_fact.get("column_label") or ""),
                        table_title=str(table_fact.get("table_title") or ""),
                        page_number=str(table_fact.get("page_number") or ""),
                        sheet_name=str(table_fact.get("sheet_name") or ""),
                        cell_reference=str(table_fact.get("cell_reference") or ""),
                        currency=str(table_fact.get("currency") or ""),
                        definition=str(table_fact.get("definition") or ""),
                        period_start=str(table_fact.get("period_start") or ""),
                        period_end=str(table_fact.get("period_end") or ""),
                        fiscal_period=str(table_fact.get("fiscal_period") or ""),
                        instant_or_duration=str(table_fact.get("instant_or_duration") or ""),
                        consolidation_scope=str(table_fact.get("consolidation_scope") or ""),
                    )

        if ticker == "CRWD":
            for row in docs:
                if str(row.get("source_type") or "") not in {
                    "latest_annual_filing",
                    "latest_quarterly_filing",
                    "latest_earnings_release",
                    "latest_investor_presentation",
                    "latest_guidance",
                }:
                    continue
                for table_fact in _extract_crwd_table_rows(row):
                    add_fact(
                        normalized_field=str(table_fact.get("normalized_field") or ""),
                        value=table_fact.get("value"),
                        unit=str(table_fact.get("unit") or ""),
                        period=str(table_fact.get("period") or "latest"),
                        source_document_id=str(table_fact.get("source_document_id") or ""),
                        source_url=str(table_fact.get("source_url") or ""),
                        source_date=str(row.get("document_date") or ""),
                        confidence=float(table_fact.get("confidence") or 0.0),
                        extraction_method=str(table_fact.get("extraction_method") or "html_table_row_match"),
                        raw_text_reference=str(table_fact.get("matched_text") or ""),
                        fact_status=str(table_fact.get("fact_status") or "verified"),
                        original_field=str(table_fact.get("row_label") or table_fact.get("normalized_field") or ""),
                        taxonomy="table",
                        source_type="crwd_table",
                        local_cache_path=str(table_fact.get("local_cache_path") or ""),
                        matched_text=str(table_fact.get("matched_text") or ""),
                        row_label=str(table_fact.get("row_label") or ""),
                        column_label=str(table_fact.get("column_label") or ""),
                        table_title=str(table_fact.get("table_title") or ""),
                        page_number=str(table_fact.get("page_number") or ""),
                        sheet_name=str(table_fact.get("sheet_name") or ""),
                        cell_reference=str(table_fact.get("cell_reference") or ""),
                        currency=str(table_fact.get("currency") or ""),
                        definition=str(table_fact.get("definition") or ""),
                        period_start=str(table_fact.get("period_start") or ""),
                        period_end=str(table_fact.get("period_end") or ""),
                        fiscal_period=str(table_fact.get("fiscal_period") or ""),
                        instant_or_duration=str(table_fact.get("instant_or_duration") or ""),
                        consolidation_scope=str(table_fact.get("consolidation_scope") or ""),
                    )

        if ticker == "OPRA":
            for row in docs:
                if str(row.get("source_type") or "") not in {
                    "latest_annual_filing",
                    "latest_quarterly_filing",
                    "latest_earnings_release",
                    "latest_investor_presentation",
                    "latest_guidance",
                }:
                    continue
                for table_fact in _extract_opra_table_rows(row):
                    add_fact(
                        normalized_field=str(table_fact.get("normalized_field") or ""),
                        value=table_fact.get("value"),
                        unit=str(table_fact.get("unit") or ""),
                        period=str(table_fact.get("period") or "latest"),
                        source_document_id=str(table_fact.get("source_document_id") or ""),
                        source_url=str(table_fact.get("source_url") or ""),
                        source_date=str(row.get("document_date") or ""),
                        confidence=float(table_fact.get("confidence") or 0.0),
                        extraction_method=str(table_fact.get("extraction_method") or "html_table_row_match"),
                        raw_text_reference=str(table_fact.get("matched_text") or ""),
                        fact_status=str(table_fact.get("fact_status") or "verified"),
                        original_field=str(table_fact.get("row_label") or table_fact.get("normalized_field") or ""),
                        taxonomy="table",
                        source_type="opra_table",
                        local_cache_path=str(table_fact.get("local_cache_path") or ""),
                        matched_text=str(table_fact.get("matched_text") or ""),
                        row_label=str(table_fact.get("row_label") or ""),
                        column_label=str(table_fact.get("column_label") or ""),
                        table_title=str(table_fact.get("table_title") or ""),
                        page_number=str(table_fact.get("page_number") or ""),
                        sheet_name=str(table_fact.get("sheet_name") or ""),
                        cell_reference=str(table_fact.get("cell_reference") or ""),
                        currency=str(table_fact.get("currency") or ""),
                        definition=str(table_fact.get("definition") or ""),
                        period_start=str(table_fact.get("period_start") or ""),
                        period_end=str(table_fact.get("period_end") or ""),
                        fiscal_period=str(table_fact.get("fiscal_period") or ""),
                        instant_or_duration=str(table_fact.get("instant_or_duration") or ""),
                        consolidation_scope=str(table_fact.get("consolidation_scope") or ""),
                    )

        if ticker == "NBIS":
            for row in docs:
                if str(row.get("source_type") or "") not in {
                    "latest_annual_filing",
                    "latest_quarterly_filing",
                    "latest_earnings_release",
                    "latest_investor_presentation",
                    "latest_guidance",
                }:
                    continue
                for table_fact in _extract_nbis_table_rows(row):
                    add_fact(
                        normalized_field=str(table_fact.get("normalized_field") or ""),
                        value=table_fact.get("value"),
                        unit=str(table_fact.get("unit") or ""),
                        period=str(table_fact.get("period") or "latest"),
                        source_document_id=str(table_fact.get("source_document_id") or ""),
                        source_url=str(table_fact.get("source_url") or ""),
                        source_date=str(row.get("document_date") or ""),
                        confidence=float(table_fact.get("confidence") or 0.0),
                        extraction_method=str(table_fact.get("extraction_method") or "html_table_row_match"),
                        raw_text_reference=str(table_fact.get("matched_text") or ""),
                        fact_status=str(table_fact.get("fact_status") or "verified"),
                        original_field=str(table_fact.get("row_label") or table_fact.get("normalized_field") or ""),
                        taxonomy="table",
                        source_type="nbis_table",
                        local_cache_path=str(table_fact.get("local_cache_path") or ""),
                        matched_text=str(table_fact.get("matched_text") or ""),
                        row_label=str(table_fact.get("row_label") or ""),
                        column_label=str(table_fact.get("column_label") or ""),
                        table_title=str(table_fact.get("table_title") or ""),
                        page_number=str(table_fact.get("page_number") or ""),
                        sheet_name=str(table_fact.get("sheet_name") or ""),
                        cell_reference=str(table_fact.get("cell_reference") or ""),
                        currency=str(table_fact.get("currency") or ""),
                        definition=str(table_fact.get("definition") or ""),
                        period_start=str(table_fact.get("period_start") or ""),
                        period_end=str(table_fact.get("period_end") or ""),
                        fiscal_period=str(table_fact.get("fiscal_period") or ""),
                        instant_or_duration=str(table_fact.get("instant_or_duration") or ""),
                        consolidation_scope=str(table_fact.get("consolidation_scope") or ""),
                    )

        if ticker == "ARTV":
            emitted_artv_fields: set[str] = set()
            for row in docs:
                if str(row.get("source_type") or "") not in {
                    "latest_annual_filing",
                    "latest_quarterly_filing",
                    "latest_earnings_release",
                    "latest_investor_presentation",
                    "latest_guidance",
                    "official_pipeline_page",
                }:
                    continue
                for table_fact in _extract_artv_table_rows(row):
                    normalized_field = str(table_fact.get("normalized_field") or "")
                    if not normalized_field or normalized_field in emitted_artv_fields:
                        continue
                    emitted_artv_fields.add(normalized_field)
                    add_fact(
                        normalized_field=normalized_field,
                        value=table_fact.get("value"),
                        unit=str(table_fact.get("unit") or "text"),
                        period=str(table_fact.get("period") or "latest"),
                        source_document_id=str(table_fact.get("source_document_id") or ""),
                        source_url=str(table_fact.get("source_url") or ""),
                        source_date=str(row.get("document_date") or ""),
                        confidence=float(table_fact.get("confidence") or 0.0),
                        extraction_method=str(table_fact.get("extraction_method") or "html_table_row_match"),
                        raw_text_reference=str(table_fact.get("matched_text") or ""),
                        fact_status=str(table_fact.get("fact_status") or "verified"),
                        original_field=str(table_fact.get("row_label") or table_fact.get("normalized_field") or ""),
                        taxonomy="table",
                        source_type="artv_table",
                        local_cache_path=str(table_fact.get("local_cache_path") or ""),
                        matched_text=str(table_fact.get("matched_text") or ""),
                        row_label=str(table_fact.get("row_label") or ""),
                        column_label=str(table_fact.get("column_label") or ""),
                        table_title=str(table_fact.get("table_title") or ""),
                        page_number=str(table_fact.get("page_number") or ""),
                        sheet_name=str(table_fact.get("sheet_name") or ""),
                        cell_reference=str(table_fact.get("cell_reference") or ""),
                        currency=str(table_fact.get("currency") or ""),
                        definition=str(table_fact.get("definition") or ""),
                        period_start=str(table_fact.get("period_start") or ""),
                        period_end=str(table_fact.get("period_end") or ""),
                        fiscal_period=str(table_fact.get("fiscal_period") or ""),
                        instant_or_duration=str(table_fact.get("instant_or_duration") or ""),
                        consolidation_scope=str(table_fact.get("consolidation_scope") or ""),
                    )

            debt_fact = next((f for f in facts if f.normalized_field == "debt" and f.fact_status == "verified"), None)
            if debt_fact is None:
                lease_debt_val, lease_period, lease_filed, lease_taxonomy, lease_alias, lease_unit, lease_ref = self._extract_latest_companyfact(
                    companyfacts,
                    {"us-gaap": ["OperatingLeaseLiability", "OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiabilityCurrent"]},
                    ["USD"],
                )
                if lease_debt_val is not None:
                    src = companyfacts_doc or {}
                    unit = lease_unit or "USD"
                    add_fact(
                        normalized_field="debt",
                        value=lease_debt_val,
                        unit=unit,
                        period=lease_period or "latest",
                        source_document_id=str(src.get("document_id") or ""),
                        source_url=str(src.get("source_url") or ""),
                        source_date=lease_filed or str(src.get("document_date") or ""),
                        confidence=88.0,
                        extraction_method="xbrl_concept_latest",
                        raw_text_reference=lease_ref,
                        fact_status="verified",
                        original_field=lease_alias or "debt",
                        taxonomy=lease_taxonomy or "us-gaap",
                        source_type=str(src.get("source_type") or ""),
                        local_cache_path=str(src.get("local_cache_path") or ""),
                        currency=_infer_currency(unit),
                        definition="lease_liability_debt_proxy",
                    )

            marketable_fact = next((f for f in facts if f.normalized_field == "marketable_securities" and f.fact_status == "verified"), None)
            if marketable_fact is None:
                mkt_val, mkt_period, mkt_filed, mkt_taxonomy, mkt_alias, mkt_unit, mkt_ref = self._extract_latest_companyfact(
                    companyfacts,
                    {"us-gaap": ["ShortTermInvestments"]},
                    ["USD"],
                )
                if mkt_val is not None:
                    src = companyfacts_doc or {}
                    unit = mkt_unit or "USD"
                    add_fact(
                        normalized_field="marketable_securities",
                        value=mkt_val,
                        unit=unit,
                        period=mkt_period or "latest",
                        source_document_id=str(src.get("document_id") or ""),
                        source_url=str(src.get("source_url") or ""),
                        source_date=mkt_filed or str(src.get("document_date") or ""),
                        confidence=88.0,
                        extraction_method="xbrl_concept_latest",
                        raw_text_reference=mkt_ref,
                        fact_status="verified",
                        original_field=mkt_alias or "marketable_securities",
                        taxonomy=mkt_taxonomy or "us-gaap",
                        source_type=str(src.get("source_type") or ""),
                        local_cache_path=str(src.get("local_cache_path") or ""),
                        currency=_infer_currency(unit),
                        definition="short_term_investments_proxy",
                    )

        def add_text_number(field: str, patterns: List[str], unit: str = "USD", percent: bool = False, confidence: float = 76.0) -> None:
            matches = self._extract_text_matches(text_rows, patterns, percent=percent, string_only=False)
            if not matches:
                add_fact(
                    normalized_field=field,
                    value=None,
                    unit="percent" if percent else unit,
                    period="latest",
                    source_document_id="",
                    source_url="",
                    source_date="",
                    confidence=0.0,
                    extraction_method="official_document_regex",
                    raw_text_reference="",
                    fact_status="missing",
                    original_field=field,
                    taxonomy="text",
                )
                return
            for match in matches:
                add_fact(
                    normalized_field=field,
                    value=match.get("value"),
                    unit="percent" if percent else unit,
                    period=str(match.get("source_date") or match.get("source_document_id") or "latest"),
                    source_document_id=str(match.get("source_document_id") or ""),
                    source_url=str(match.get("source_url") or ""),
                    source_date=str(match.get("source_date") or ""),
                    confidence=confidence if match.get("value") is not None else 0.0,
                    extraction_method="official_document_regex",
                    raw_text_reference=str(match.get("matched_text") or ""),
                    fact_status="uncertain" if match.get("value") is not None else "missing",
                    original_field=field,
                    taxonomy="text",
                    source_type=str(match.get("source_type") or ""),
                    local_cache_path=str(match.get("local_cache_path") or ""),
                    matched_text=str(match.get("matched_text") or ""),
                    context_before=str(match.get("context_before") or ""),
                    context_after=str(match.get("context_after") or ""),
                    source_location=str(match.get("source_location") or ""),
                    extraction_rule=str(match.get("extraction_rule") or ""),
                )

        def add_text_phrase(field: str, patterns: List[str], confidence: float = 68.0) -> None:
            matches = self._extract_text_matches(text_rows, patterns, string_only=True)
            if not matches:
                add_fact(
                    normalized_field=field,
                    value=None,
                    unit="text",
                    period="latest",
                    source_document_id="",
                    source_url="",
                    source_date="",
                    confidence=0.0,
                    extraction_method="official_document_regex",
                    raw_text_reference="",
                    fact_status="missing",
                    original_field=field,
                    taxonomy="text",
                )
                return
            for match in matches:
                add_fact(
                    normalized_field=field,
                    value=match.get("value"),
                    unit="text",
                    period=str(match.get("source_date") or match.get("source_document_id") or "latest"),
                    source_document_id=str(match.get("source_document_id") or ""),
                    source_url=str(match.get("source_url") or ""),
                    source_date=str(match.get("source_date") or ""),
                    confidence=confidence,
                    extraction_method="official_document_regex",
                    raw_text_reference=str(match.get("matched_text") or ""),
                    fact_status="uncertain",
                    original_field=field,
                    taxonomy="text",
                    source_type=str(match.get("source_type") or ""),
                    local_cache_path=str(match.get("local_cache_path") or ""),
                    matched_text=str(match.get("matched_text") or ""),
                    context_before=str(match.get("context_before") or ""),
                    context_after=str(match.get("context_after") or ""),
                    source_location=str(match.get("source_location") or ""),
                    extraction_rule=str(match.get("extraction_rule") or ""),
                )

        if security_type == "operating_company":
            add_text_phrase("guidance", [r"guidance[^.]{0,200}\.", r"outlook[^.]{0,200}\."])
            if ticker == "CRWD":
                add_text_number("arr", [r"annual recurring revenue[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)", r"\bARR\b[^$]{0,30}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
                add_text_number("subscription_revenue", [r"subscription revenue[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
                add_text_number("customer_count", [r"([0-9][0-9,]{2,}\+?)\s+(?:subscription\s+)?customers", r"(?:more than|over)\s+([0-9][0-9,]{2,}\+?)\s+(?:subscription\s+)?customers"], unit="count")
                add_text_number("retention", [r"retention[^0-9]{0,20}([0-9]{1,3}\.?[0-9]*)%", r"net retention[^0-9]{0,20}([0-9]{1,3}\.?[0-9]*)%"], unit="percent", percent=True)
                add_text_number("buybacks", [r"repurchas(?:e|ed)[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)", r"share repurchase[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
            if ticker == "NBIS":
                add_text_number("revenue_by_segment", [r"segment[^$]{0,80}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
                add_text_number("ai_infrastructure_revenue", [r"AI infrastructure[^$]{0,80}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
                for src in text_rows:
                    cache_path = str(src.get("local_cache_path") or "")
                    if not cache_path:
                        continue
                    p = Path(cache_path)
                    if not p.exists():
                        continue
                    raw = p.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r'name="us-gaap:ConcentrationRiskPercentage1"[^>]*>([0-9]{1,3}\.?[0-9]*)</ix:nonFraction>%?', raw, flags=re.IGNORECASE)
                    if not m:
                        continue
                    try:
                        val = float(m.group(1))
                    except ValueError:
                        continue
                    start = m.start(0)
                    end = m.end(0)
                    add_fact(
                        normalized_field="customer_concentration",
                        value=val,
                        unit="percent",
                        period=str(src.get("document_date") or src.get("document_id") or "latest"),
                        source_document_id=str(src.get("document_id") or ""),
                        source_url=str(src.get("source_url") or ""),
                        source_date=str(src.get("document_date") or ""),
                        confidence=92.0,
                        extraction_method="inline_xbrl_regex",
                        raw_text_reference=m.group(0)[:240],
                        fact_status="verified",
                        original_field="customer_concentration",
                        taxonomy="inline_xbrl",
                        source_type=str(src.get("source_type") or ""),
                        local_cache_path=cache_path,
                        matched_text=m.group(0)[:240],
                        context_before=raw[max(0, start - 140):start].strip(),
                        context_after=raw[end:min(len(raw), end + 140)].strip(),
                        source_location=f"char:{start}",
                        extraction_rule='name="us-gaap:ConcentrationRiskPercentage1"...<ix:nonFraction>',
                    )
                add_text_number("customer_concentration", [r"([0-9]{1,3}\.?[0-9]*)%\s+of\s+revenue\s+from\s+(?:a\s+)?single\s+customer"], unit="percent", percent=True)
            if ticker == "OPRA":
                add_text_number("advertising_revenue", [r"advertising revenue[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
                add_text_number("search_revenue", [r"search revenue[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
                add_text_number("dividends", [r"dividend[s]?[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
                add_text_number("buybacks", [r"repurchas(?:e|ed)[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)", r"share repurchase[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
        if ticker == "RKLB":
            for row in docs:
                if str(row.get("source_type") or "") not in {
                    "latest_annual_filing",
                    "latest_quarterly_filing",
                    "latest_earnings_release",
                    "latest_investor_presentation",
                    "latest_guidance",
                    "official_ir_page",
                }:
                    continue
                for table_fact in _extract_rklb_table_rows(row):
                    add_fact(
                        normalized_field=str(table_fact.get("normalized_field") or ""),
                        value=table_fact.get("value"),
                        unit=str(table_fact.get("unit") or ""),
                        period=str(table_fact.get("period") or "latest"),
                        source_document_id=str(table_fact.get("source_document_id") or ""),
                        source_url=str(table_fact.get("source_url") or ""),
                        source_date=str(row.get("document_date") or ""),
                        confidence=float(table_fact.get("confidence") or 0.0),
                        extraction_method=str(table_fact.get("extraction_method") or "html_table_row_match"),
                        raw_text_reference=str(table_fact.get("matched_text") or ""),
                        fact_status=str(table_fact.get("fact_status") or "verified"),
                        original_field=str(table_fact.get("row_label") or table_fact.get("normalized_field") or ""),
                        taxonomy="table",
                        source_type="rklb_table",
                        local_cache_path=str(table_fact.get("local_cache_path") or ""),
                        matched_text=str(table_fact.get("matched_text") or ""),
                        row_label=str(table_fact.get("row_label") or ""),
                        column_label=str(table_fact.get("column_label") or ""),
                        table_title=str(table_fact.get("table_title") or ""),
                        page_number=str(table_fact.get("page_number") or ""),
                        sheet_name=str(table_fact.get("sheet_name") or ""),
                        cell_reference=str(table_fact.get("cell_reference") or ""),
                        currency=str(table_fact.get("currency") or ""),
                        definition=str(table_fact.get("definition") or ""),
                        period_start=str(table_fact.get("period_start") or ""),
                        period_end=str(table_fact.get("period_end") or ""),
                        fiscal_period=str(table_fact.get("fiscal_period") or ""),
                        instant_or_duration=str(table_fact.get("instant_or_duration") or ""),
                        consolidation_scope=str(table_fact.get("consolidation_scope") or ""),
                    )

            add_text_number("backlog", [r"backlog[^$]{0,80}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"], unit="USD")
            add_text_number("adjusted_ebitda", [r"adjusted EBITDA[^$]{0,80}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"], unit="USD")
            add_text_number("launch_services_revenue", [r"launch services revenue[^$]{0,80}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"], unit="USD")
            add_text_number("space_systems_revenue", [r"space systems revenue[^$]{0,80}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"], unit="USD")
            add_text_phrase("spacecraft", [r"\bspacecraft\b[^.]{0,160}\."], confidence=70.0)
            add_text_phrase("electron", [r"\bElectron\b[^.]{0,160}\."], confidence=70.0)
            add_text_phrase("neutron", [r"\bNeutron\b[^.]{0,160}\."], confidence=70.0)

        if security_type == "bank":
            add_text_phrase("guidance", [r"guidance[^.]{0,200}\.", r"outlook[^.]{0,200}\."])

            bank_verified = {f.normalized_field: f for f in facts if f.fact_status == "verified"}
            common_equity_fact = bank_verified.get("common_equity")
            goodwill_fact = bank_verified.get("goodwill")
            intangible_fact = bank_verified.get("intangible_assets")
            share_count_fact = bank_verified.get("diluted_share_count") or bank_verified.get("share_count")

            if common_equity_fact and goodwill_fact and intangible_fact and common_equity_fact.currency == goodwill_fact.currency == intangible_fact.currency:
                tangible_value = float(common_equity_fact.value) - float(goodwill_fact.value) - float(intangible_fact.value)
                calc_meta = {
                    "formula": "tangible_common_equity = common_equity - goodwill - intangible_assets",
                    "inputs": ["common_equity", "goodwill", "intangible_assets"],
                    "input_values": [common_equity_fact.value, goodwill_fact.value, intangible_fact.value],
                    "input_currencies": [common_equity_fact.currency, goodwill_fact.currency, intangible_fact.currency],
                    "input_periods": [common_equity_fact.period, goodwill_fact.period, intangible_fact.period],
                    "calculation_timestamp": _utc_now_iso(),
                }
                add_fact(
                    normalized_field="tangible_common_equity",
                    value=tangible_value,
                    unit=common_equity_fact.unit,
                    period=common_equity_fact.period,
                    source_document_id=common_equity_fact.source_document_id,
                    source_url=common_equity_fact.source_url,
                    source_date=common_equity_fact.source_date,
                    confidence=90.0,
                    extraction_method="derived_from_verified_facts",
                    raw_text_reference="tangible_common_equity=common_equity-goodwill-intangible_assets",
                    fact_status="verified",
                    original_field="tangible_common_equity",
                    taxonomy="derived",
                    source_type=common_equity_fact.source_type,
                    local_cache_path=common_equity_fact.local_cache_path,
                    currency=common_equity_fact.currency,
                    calculation_metadata=calc_meta,
                )
                add_fact(
                    normalized_field="tangible_book_value",
                    value=tangible_value,
                    unit=common_equity_fact.unit,
                    period=common_equity_fact.period,
                    source_document_id=common_equity_fact.source_document_id,
                    source_url=common_equity_fact.source_url,
                    source_date=common_equity_fact.source_date,
                    confidence=90.0,
                    extraction_method="derived_from_verified_facts",
                    raw_text_reference="tangible_book_value=tangible_common_equity",
                    fact_status="verified",
                    original_field="tangible_book_value",
                    taxonomy="derived",
                    source_type=common_equity_fact.source_type,
                    local_cache_path=common_equity_fact.local_cache_path,
                    currency=common_equity_fact.currency,
                    calculation_metadata=calc_meta,
                )
                if share_count_fact and float(share_count_fact.value or 0) != 0:
                    add_fact(
                        normalized_field="tbv_per_share",
                        value=tangible_value / float(share_count_fact.value),
                        unit=common_equity_fact.unit,
                        period=common_equity_fact.period,
                        source_document_id=common_equity_fact.source_document_id,
                        source_url=common_equity_fact.source_url,
                        source_date=common_equity_fact.source_date,
                        confidence=88.0,
                        extraction_method="derived_from_verified_facts",
                        raw_text_reference="tbv_per_share=tangible_book_value/diluted_share_count",
                        fact_status="verified",
                        original_field="tbv_per_share",
                        taxonomy="derived",
                        source_type=common_equity_fact.source_type,
                        local_cache_path=common_equity_fact.local_cache_path,
                        currency=common_equity_fact.currency,
                        calculation_metadata={
                            "formula": "tbv_per_share = tangible_book_value / diluted_share_count",
                            "inputs": ["tangible_book_value", "diluted_share_count"],
                            "input_values": [tangible_value, share_count_fact.value],
                            "input_currencies": [common_equity_fact.currency, share_count_fact.currency],
                            "input_periods": [common_equity_fact.period, share_count_fact.period],
                            "calculation_timestamp": _utc_now_iso(),
                        },
                    )

            loans_series = self._extract_series(companyfacts, XBRL_FIELD_MAPPINGS["loans"]["aliases"], ["CAD", "USD"])
            if len(loans_series) >= 2 and loans_series[-2][2] != 0:
                add_fact(
                    normalized_field="loan_growth",
                    value=((loans_series[-1][2] - loans_series[-2][2]) / abs(loans_series[-2][2])) * 100.0,
                    unit="percent",
                    period=loans_series[-1][0],
                    source_document_id=str(companyfacts_doc.get("document_id") if companyfacts_doc else ""),
                    source_url=str(companyfacts_doc.get("source_url") if companyfacts_doc else ""),
                    source_date=loans_series[-1][1],
                    confidence=88.0,
                    extraction_method="derived_from_companyfacts_series",
                    raw_text_reference="loan_growth=(current-prior)/prior",
                    fact_status="verified",
                    original_field="loan_growth",
                    taxonomy="derived",
                    source_type=str(companyfacts_doc.get("source_type") if companyfacts_doc else ""),
                    local_cache_path=str(companyfacts_doc.get("local_cache_path") if companyfacts_doc else ""),
                    currency="CAD",
                    calculation_metadata={
                        "formula": "loan_growth = (current_loans - prior_loans) / prior_loans",
                        "input_values": [loans_series[-1][2], loans_series[-2][2]],
                        "input_currencies": ["CAD", "CAD"],
                        "input_periods": [loans_series[-1][0], loans_series[-2][0]],
                        "calculation_timestamp": _utc_now_iso(),
                    },
                )

            deposits_series = self._extract_series(companyfacts, XBRL_FIELD_MAPPINGS["deposits"]["aliases"], ["CAD", "USD"])
            if len(deposits_series) >= 2 and deposits_series[-2][2] != 0:
                add_fact(
                    normalized_field="deposit_growth",
                    value=((deposits_series[-1][2] - deposits_series[-2][2]) / abs(deposits_series[-2][2])) * 100.0,
                    unit="percent",
                    period=deposits_series[-1][0],
                    source_document_id=str(companyfacts_doc.get("document_id") if companyfacts_doc else ""),
                    source_url=str(companyfacts_doc.get("source_url") if companyfacts_doc else ""),
                    source_date=deposits_series[-1][1],
                    confidence=88.0,
                    extraction_method="derived_from_companyfacts_series",
                    raw_text_reference="deposit_growth=(current-prior)/prior",
                    fact_status="verified",
                    original_field="deposit_growth",
                    taxonomy="derived",
                    source_type=str(companyfacts_doc.get("source_type") if companyfacts_doc else ""),
                    local_cache_path=str(companyfacts_doc.get("local_cache_path") if companyfacts_doc else ""),
                    currency="CAD",
                    calculation_metadata={
                        "formula": "deposit_growth = (current_deposits - prior_deposits) / prior_deposits",
                        "input_values": [deposits_series[-1][2], deposits_series[-2][2]],
                        "input_currencies": ["CAD", "CAD"],
                        "input_periods": [deposits_series[-1][0], deposits_series[-2][0]],
                        "calculation_timestamp": _utc_now_iso(),
                    },
                )

        if security_type == "biotechnology":
            add_text_number("quarterly_operating_cash_flow", [r"cash flows from (?:used in )?operating activities[^$]{0,40}(\$[0-9.,]+\s*(?:million|billion|m|b)?)"])
            add_text_phrase("estimated_cash_runway", [r"cash runway[^.]{0,60}[0-9]{1,2}\s*(?:months|years)"])
            add_text_phrase("pipeline_programs", [r"pipeline[^.]{0,220}\."])
            add_text_phrase("development_stage", [r"Phase\s+[1-3][^.]{0,120}\."])
            add_text_phrase("trial_phase", [r"Phase\s+[1-3][^.]{0,120}\."])
            add_text_phrase("enrollment_status", [r"enrollment[^.]{0,180}\."])
            add_text_phrase("expected_data_readouts", [r"data readout[^.]{0,180}\."])
            add_text_phrase("regulatory_designations", [r"(?:Fast Track|Breakthrough|orphan drug)[^.]{0,180}\."])
            add_text_phrase("partnerships", [r"partnership[^.]{0,180}\."])
            add_text_phrase("licensing_agreements", [r"licens(?:e|ing) agreement[^.]{0,180}\."])
            add_text_phrase("recent_financing", [r"financing[^.]{0,200}\."])
            add_text_phrase("management_stated_dilution_disclosures", [r"dilution[^.]{0,180}\."])

            if ticker == "ARTV":
                verified_now = {f.normalized_field: f for f in facts if f.fact_status == "verified"}
                if "estimated_cash_runway" not in verified_now and "cash" in verified_now and "quarterly_operating_cash_flow" in verified_now:
                    burn_val = float(verified_now["quarterly_operating_cash_flow"].value or 0)
                    if burn_val < 0:
                        total_liquidity = float(verified_now["cash"].value or 0)
                        if "marketable_securities" in verified_now:
                            total_liquidity += float(verified_now["marketable_securities"].value or 0)
                        if total_liquidity > 0:
                            runway_months = (total_liquidity / abs(burn_val)) * 3.0
                            add_fact(
                                normalized_field="estimated_cash_runway",
                                value=runway_months,
                                unit="months",
                                period=verified_now["cash"].period,
                                source_document_id=verified_now["cash"].source_document_id,
                                source_url=verified_now["cash"].source_url,
                                source_date=verified_now["cash"].source_date,
                                confidence=86.0,
                                extraction_method="derived_from_verified_facts",
                                raw_text_reference="estimated_cash_runway=(cash+marketable_securities)/abs(quarterly_operating_cash_flow)*3",
                                fact_status="verified",
                                original_field="estimated_cash_runway",
                                taxonomy="derived",
                                source_type=verified_now["cash"].source_type,
                                local_cache_path=verified_now["cash"].local_cache_path,
                                definition="cash_runway_derived_from_liquidity_and_burn",
                                calculation_metadata={
                                    "formula": "cash_runway_months = (cash + marketable_securities) / abs(quarterly_operating_cash_flow) * 3",
                                    "inputs": ["cash", "marketable_securities", "quarterly_operating_cash_flow"],
                                    "input_values": [
                                        verified_now["cash"].value,
                                        verified_now.get("marketable_securities").value if verified_now.get("marketable_securities") else 0,
                                        verified_now["quarterly_operating_cash_flow"].value,
                                    ],
                                    "input_periods": [
                                        verified_now["cash"].period,
                                        verified_now.get("marketable_securities").period if verified_now.get("marketable_securities") else verified_now["cash"].period,
                                        verified_now["quarterly_operating_cash_flow"].period,
                                    ],
                                    "calculation_timestamp": _utc_now_iso(),
                                },
                            )

        if security_type == "etf_fund":
            add_text_phrase("fund_strategy", [r"investment objective[^.]{0,240}\.", r"fund seeks to[^.]{0,240}\."])
            add_text_phrase("fund_type", [r"exchange-traded fund[^.]{0,120}\.", r"ETF[^.]{0,80}\."])
            add_text_phrase("benchmark", [r"benchmark[^.]{0,200}\.", r"index[^.]{0,180}\."])
            add_text_phrase("fund_sponsor", [r"Defiance[^.]{0,120}\.", r"sponsor[^.]{0,120}\."])
            add_text_phrase("advisor", [r"adviser[^.]{0,120}\.", r"advisor[^.]{0,120}\."])
            add_text_number("top_ten_concentration", [r"top\s*10[^0-9]{0,40}([0-9]{1,3}\.?[0-9]*)%"], unit="percent", percent=True)
            add_text_number("number_of_holdings", [r"([0-9]{1,4})\s+holdings"], unit="count")

        finviz = self._extract_from_finviz(docs)
        market_doc = source_by_type.get("market_data") or {}

        def finviz_numeric(key: str) -> Any:
            raw = finviz.get(key)
            return FinvizDataSource._parse_numeric_value(raw) if raw is not None else None

        for field_name, finviz_key, unit in [
            ("assets_under_management", "AUM", "USD"),
            ("average_daily_volume", "Avg Volume", "shares"),
            ("expense_ratio", "Expense", "percent"),
            ("distribution_yield", "Dividend %", "percent"),
        ]:
            value = finviz_numeric(finviz_key)
            status = "verified" if value is not None else "missing"
            if security_type == "etf_fund" and field_name in {"assets_under_management", "expense_ratio", "distribution_yield"}:
                status = "uncertain" if value is not None else "missing"
            add_fact(
                normalized_field=field_name,
                value=value,
                unit=unit,
                period="latest",
                source_document_id=str(market_doc.get("document_id") or ""),
                source_url=str(market_doc.get("source_url") or ""),
                source_date=str(market_doc.get("document_date") or ""),
                confidence=78.0 if value is not None else 0.0,
                extraction_method="finviz_snapshot",
                raw_text_reference=f"finviz:{finviz_key}",
                fact_status=status,
                original_field=finviz_key,
                taxonomy="market_data",
                source_type=str(market_doc.get("source_type") or ""),
                local_cache_path=str(market_doc.get("local_cache_path") or ""),
                currency=_infer_currency(unit),
            )

        # Post-process: explicit N/A tagging for truly non-applicable fields.
        known_na = {
            "SPCX": ["buybacks", "arr", "subscription_revenue", "customer_count", "retention"],
            "VBNK": ["arr", "subscription_revenue", "search_revenue", "advertising_revenue"],
        }
        for field in known_na.get(ticker, []):
            add_fact(
                normalized_field=field,
                value=None,
                unit="",
                period="latest",
                source_document_id="",
                source_url="",
                source_date="",
                confidence=100.0,
                extraction_method="applicability_rule",
                raw_text_reference="security_type_not_applicable",
                fact_status="not_applicable",
                original_field=field,
                taxonomy="rule",
            )

        # Ensure required and optional field presence.
        required_fields = required_fields_for_ticker(ticker, security_type)
        optional_fields = optional_fields_for_ticker(ticker)
        existing_fields = {f.normalized_field for f in facts}
        for field in required_fields + optional_fields:
            if field in existing_fields:
                continue
            add_fact(
                normalized_field=field,
                value=None,
                unit="",
                period="latest",
                source_document_id="",
                source_url="",
                source_date="",
                confidence=0.0,
                extraction_method="coverage_padding",
                raw_text_reference="",
                fact_status="missing",
                original_field=field,
                taxonomy="coverage",
            )

        # Conflict handling per normalized field and period.
        by_key: Dict[Tuple[str, str, str, str, str, str], List[Phase1Fact]] = {}
        for f in facts:
            by_key.setdefault(
                (
                    f.normalized_field,
                    f.definition,
                    f.period_start or f.period,
                    f.period_end or f.period,
                    f.currency,
                    f.consolidation_scope,
                ),
                [],
            ).append(f)

        for _, rows in by_key.items():
            vals = {str(r.value) for r in rows if r.fact_status in {"verified", "uncertain"} and r.value is not None}
            if len(vals) > 1:
                for r in rows:
                    if r.fact_status in {"verified", "uncertain"}:
                        r.fact_status = "conflicting"

        payload = {
            "ticker": ticker,
            "security_type": security_type,
            "parsed_at": _utc_now_iso(),
            "facts": [f.as_dict() for f in facts],
        }
        _json_dump(FACTS_DIR / f"{ticker}_phase1_facts.json", payload)
        return payload


def _classify_source_failure(error: str, source_type: str, ticker: str) -> str:
    err = str(error or "").lower()
    st = str(source_type or "").lower()
    if not err:
        return "unknown"
    if "not configured" in err or "no matching filing" in err:
        if ticker in {"NBIS", "OPRA", "VBNK"} and ("quarterly" in st or "annual" in st):
            return "foreign issuer form mismatch"
        return "source not found"
    if "403" in err or "404" in err or "timed out" in err or "ssl" in err:
        return "source inaccessible"
    if "unsupported" in err:
        return "parser unsupported"
    if "cik" in err:
        return "identifier mismatch"
    if "fund" in st and "format" in err:
        return "fund document format unsupported"
    return "source not found"


def _coverage_from_fields(facts: List[Dict[str, Any]], fields: List[str]) -> Dict[str, Any]:
    status_by_field: Dict[str, str] = {}
    for field in fields:
        status_by_field[field] = "missing"

    priority = {"verified": 5, "conflicting": 4, "uncertain": 3, "not_applicable": 2, "missing": 1}
    for f in facts:
        field = str(f.get("normalized_field") or f.get("field") or "")
        if field not in status_by_field:
            continue
        st = str(f.get("fact_status") or "missing")
        if priority.get(st, 0) > priority.get(status_by_field[field], 0):
            status_by_field[field] = st

    verified = [k for k, v in status_by_field.items() if v == "verified"]
    uncertain = [k for k, v in status_by_field.items() if v == "uncertain"]
    conflicting = [k for k, v in status_by_field.items() if v == "conflicting"]
    missing = [k for k, v in status_by_field.items() if v == "missing"]
    not_applicable = [k for k, v in status_by_field.items() if v == "not_applicable"]

    applicable_total = len(fields) - len(not_applicable)
    verified_coverage = round((len(verified) / applicable_total) * 100.0, 1) if applicable_total > 0 else 100.0
    uncertain_coverage = round((len(uncertain) / applicable_total) * 100.0, 1) if applicable_total > 0 else 0.0
    conflicting_coverage = round((len(conflicting) / applicable_total) * 100.0, 1) if applicable_total > 0 else 0.0
    missing_coverage = round((len(missing) / applicable_total) * 100.0, 1) if applicable_total > 0 else 0.0

    return {
        "status_by_field": status_by_field,
        "verified": verified,
        "uncertain": uncertain,
        "conflicting": conflicting,
        "missing": missing,
        "not_applicable": not_applicable,
        "applicable_total": applicable_total,
        "verified_coverage_pct": verified_coverage,
        "uncertain_coverage_pct": uncertain_coverage,
        "conflicting_coverage_pct": conflicting_coverage,
        "missing_coverage_pct": missing_coverage,
    }


def _compute_phase2_readiness(
    *,
    required_cov: Dict[str, Any],
    target: float,
    conflicting_required_fields: List[str],
    source_failures: List[Dict[str, Any]],
    verified_text_facts: List[Dict[str, Any]],
    currency_ambiguity: bool,
    material_period_mismatch: bool,
    identity_status: str,
) -> bool:
    """Canonical Phase 2 readiness contract from resolved per-field coverage."""
    return bool(
        required_cov["verified_coverage_pct"] >= target
        and not required_cov["missing"]
        and not conflicting_required_fields
        and not source_failures
        and not verified_text_facts
        and not currency_ambiguity
        and not material_period_mismatch
        and identity_status == "verified"
    )


def build_phase1_report(
    ticker: str,
    security_type: str,
    collection: Dict[str, Any],
    parsed: Dict[str, Any],
    identity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    docs = list(collection.get("documents") or [])
    facts = list(parsed.get("facts") or [])

    found_docs = [d for d in docs if d.get("collection_status") in {"retrieved", "cached"}]
    missing_docs = [d for d in docs if d.get("collection_status") in {"missing", "error"}]
    source_failures = [
        {
            "source_type": d.get("source_type"),
            "source_url": d.get("source_url"),
            "error": d.get("collection_error"),
            "category": _classify_source_failure(str(d.get("collection_error") or ""), str(d.get("source_type") or ""), ticker),
        }
        for d in missing_docs
    ]

    required_fields = required_fields_for_ticker(ticker, security_type)
    optional_fields = optional_fields_for_ticker(ticker)

    required_cov = _coverage_from_fields(facts, required_fields)
    optional_cov = _coverage_from_fields(facts, optional_fields)

    verified_facts = [f for f in facts if f.get("fact_status") == "verified"]
    uncertain_facts = [f for f in facts if f.get("fact_status") == "uncertain"]
    conflicting_facts = [f for f in facts if f.get("fact_status") == "conflicting"]
    calculated_facts = [f for f in verified_facts if f.get("calculation_metadata")]
    table_facts = [f for f in facts if str(f.get("taxonomy") or "") == "table"]
    verified_text_facts = [f for f in verified_facts if f.get("extraction_method") == "official_document_regex"]
    currencies = sorted({str(f.get("currency") or "") for f in verified_facts if f.get("currency")})
    currency_ambiguity = len(currencies) > 1 and ticker == "VBNK"
    material_period_mismatch = False
    for f in verified_facts:
        calc = f.get("calculation_metadata") or {}
        periods = list(calc.get("input_periods") or [])
        if calc.get("requires_same_period") and periods and len(set(periods)) > 1:
            material_period_mismatch = True
            break

    source_dates = [str(d.get("document_date") or "") for d in found_docs if d.get("document_date")]
    latest_source_date = max(source_dates) if source_dates else ""
    freshness_status = "fresh" if latest_source_date else "unknown"

    blockers: List[str] = []
    if required_cov["missing"]:
        blockers.append("Missing required fields: " + ", ".join(required_cov["missing"][:12]))
    # Use resolved per-field status to avoid reporting stale conflicts when a field
    # also has a higher-priority verified fact in the final normalized fact store.
    conflicting_required_fields = sorted(list(required_cov["conflicting"]))
    if conflicting_required_fields:
        blockers.append("Conflicting required facts: " + ", ".join(conflicting_required_fields[:12]))
    if source_failures:
        failed_types = sorted({str(f["source_type"]) for f in source_failures if f.get("source_type")})
        blockers.append("Source failures present: " + ", ".join(failed_types[:12]))
    if verified_text_facts:
        blockers.append("Verified narrative facts remain without structured or exact table lineage")
    if currency_ambiguity:
        blockers.append("Currency ambiguity remains across verified facts")
    if material_period_mismatch:
        blockers.append("Material period mismatch remains in calculated verified facts")
    identity_status = str((identity or {}).get("identity_status") or "verified")
    if identity_status != "verified":
        blockers.append(f"Identity status is {identity_status}")

    target = COVERAGE_TARGETS.get(ticker, 100.0)
    if required_cov["verified_coverage_pct"] < target:
        blockers.append(
            f"Required verified coverage below target: {required_cov['verified_coverage_pct']}% < {target}%"
        )

    readiness = _compute_phase2_readiness(
        required_cov=required_cov,
        target=target,
        conflicting_required_fields=conflicting_required_fields,
        source_failures=source_failures,
        verified_text_facts=verified_text_facts,
        currency_ambiguity=currency_ambiguity,
        material_period_mismatch=material_period_mismatch,
        identity_status=identity_status,
    )

    summary = {
        "ticker": ticker,
        "security_type": security_type,
        "source_documents_found": len(found_docs),
        "source_documents_missing": len(missing_docs),
        "verified_facts": len(verified_facts),
        "uncertain_facts": len(uncertain_facts),
        "conflicting_facts": len(conflicting_facts),
        "required_field_coverage_pct": required_cov["verified_coverage_pct"],
        "optional_field_coverage_pct": optional_cov["verified_coverage_pct"],
        "required_uncertain_coverage_pct": required_cov["uncertain_coverage_pct"],
        "required_conflicting_coverage_pct": required_cov["conflicting_coverage_pct"],
        "required_missing_coverage_pct": required_cov["missing_coverage_pct"],
        "missing_required_facts": len(required_cov["missing"]),
        "missing_required_fields": required_cov["missing"],
        "conflicting_required_fields": conflicting_required_fields,
        "not_applicable_fields": required_cov["not_applicable"],
        "latest_source_date": latest_source_date,
        "freshness_status": freshness_status,
        "phase2_target_coverage_pct": target,
        "phase2_readiness": readiness,
        "identity_status": identity_status,
        "currency_issues": currencies if currency_ambiguity else [],
        "material_period_mismatch": material_period_mismatch,
        "blockers_for_phase2": blockers,
        "source_failures": source_failures,
    }

    lines: List[str] = []
    lines.append(f"# {ticker} Phase 1 Facts")
    lines.append("")
    lines.append(f"- Security type: {security_type}")
    lines.append(f"- Identity status: {identity_status}")
    lines.append(f"- Generated at: {_utc_now_iso()}")
    lines.append(f"- Sources attempted: {len(docs)}")
    lines.append(f"- Sources retrieved: {len(found_docs)}")
    lines.append(f"- Source failures: {len(source_failures)}")
    lines.append(f"- Verified facts: {len(verified_facts)}")
    lines.append(f"- Uncertain facts: {len(uncertain_facts)}")
    lines.append(f"- Conflicting facts: {len(conflicting_facts)}")
    lines.append(f"- Missing required facts: {len(required_cov['missing'])}")
    lines.append(f"- Not-applicable required fields: {len(required_cov['not_applicable'])}")
    lines.append(f"- Required coverage (verified only): {required_cov['verified_coverage_pct']}%")
    lines.append(f"- Optional coverage (verified only): {summary['optional_field_coverage_pct']}%")
    lines.append(f"- Required uncertain coverage: {summary['required_uncertain_coverage_pct']}%")
    lines.append(f"- Required conflicting coverage: {summary['required_conflicting_coverage_pct']}%")
    lines.append(f"- Required missing coverage: {summary['required_missing_coverage_pct']}%")
    lines.append(f"- Latest source date: {latest_source_date or 'n/a'}")
    lines.append(f"- Freshness: {freshness_status}")
    lines.append(f"- Phase 2 readiness: {readiness}")
    lines.append("")

    lines.append("## Sources Attempted")
    lines.append("")
    if docs:
        for d in docs:
            lines.append(
                f"- {d.get('source_type')} | status={d.get('collection_status')} | url={d.get('source_url') or 'n/a'}"
            )
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Source Failures")
    lines.append("")
    if source_failures:
        for f in source_failures:
            lines.append(
                f"- {f.get('source_type')} | category={f.get('category')} | error={f.get('error') or 'n/a'}"
            )
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Documents Retrieved")
    lines.append("")
    if found_docs:
        for d in found_docs:
            lines.append(f"- {d.get('source_type')} | {d.get('document_date') or 'n/a'} | {d.get('source_url') or 'n/a'}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Documents Rejected")
    lines.append("")
    if missing_docs:
        for d in missing_docs:
            lines.append(f"- {d.get('source_type')} | {d.get('collection_error') or 'n/a'}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Tables Extracted")
    lines.append("")
    if table_facts:
        for f in table_facts:
            lines.append(f"- {f.get('normalized_field')} | {f.get('table_title') or 'n/a'} | row={f.get('row_label') or 'n/a'} | col={f.get('column_label') or 'n/a'}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Missing Required Facts")
    lines.append("")
    if summary["missing_required_fields"]:
        for field in summary["missing_required_fields"]:
            lines.append(f"- {field}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Not Applicable Fields")
    lines.append("")
    if required_cov["not_applicable"]:
        for field in required_cov["not_applicable"]:
            lines.append(f"- {field}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Uncertain Facts")
    lines.append("")
    if uncertain_facts:
        for field in sorted({str(f.get('normalized_field') or f.get('field')) for f in uncertain_facts}):
            lines.append(f"- {field}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Calculated Facts")
    lines.append("")
    if calculated_facts:
        for f in calculated_facts:
            formula = ((f.get('calculation_metadata') or {}).get('formula') or 'n/a')
            lines.append(f"- {f.get('normalized_field')} | {formula}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Currency Checks")
    lines.append("")
    if currencies:
        lines.append(f"- Verified currencies present: {', '.join(currencies)}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Period Checks")
    lines.append("")
    lines.append(f"- Material period mismatch: {material_period_mismatch}")
    lines.append("")

    lines.append("## Exact Remaining Blockers")
    lines.append("")
    if summary["blockers_for_phase2"]:
        for b in summary["blockers_for_phase2"]:
            lines.append(f"- {b}")
    else:
        lines.append("- none")

    out_path = REVIEW_DIR / f"{ticker}_phase1_facts.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return summary


def run_phase1(tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    _ensure_dirs()
    tickers = tickers or list(INITIAL_TICKERS)

    collector = ResearchCollector()
    parser = ResearchParser()
    identity_registry = _build_security_identity_registry(tickers)

    per_ticker: Dict[str, Any] = {}
    all_facts: List[Dict[str, Any]] = []
    previous_facts: Dict[str, List[Dict[str, Any]]] = {}
    current_facts: Dict[str, List[Dict[str, Any]]] = {}

    for ticker in tickers:
        old_path = FACTS_DIR / f"{ticker}_phase1_facts.json"
        previous_facts[ticker] = list((_json_load(old_path, {}) or {}).get("facts") or [])

    for ticker in tickers:
        identity = identity_registry.get(ticker, {})
        security_type = str(identity.get("security_type") or infer_security_type(ticker))
        if str(identity.get("identity_status") or "") != "verified":
            collection = {"ticker": ticker, "security_type": security_type, "collected_at": _utc_now_iso(), "documents": []}
            parsed = {
                "ticker": ticker,
                "security_type": security_type,
                "parsed_at": _utc_now_iso(),
                "facts": [
                    {
                        "ticker": ticker,
                        "field": field,
                        "normalized_field": field,
                        "original_field": field,
                        "taxonomy": "identity_gate",
                        "value": None,
                        "unit": "",
                        "period": "latest",
                        "source_document_id": "",
                        "source_url": "",
                        "source_date": "",
                        "extracted_at": _utc_now_iso(),
                        "confidence": 0.0,
                        "extraction_method": "identity_gate",
                        "raw_text_reference": f"{ticker} identity unresolved or ticker reassigned",
                        "fact_status": "missing",
                        "blocker_reason": "identity_blocked",
                        "source_type": "identity_gate",
                        "local_cache_path": "",
                        "matched_text": "",
                        "context_before": "",
                        "context_after": "",
                        "source_location": "",
                        "extraction_rule": "identity_status must be verified",
                        "currency": "",
                        "calculation_metadata": {},
                    }
                    for field in required_fields_for_ticker(ticker, security_type)
                ],
            }
            _json_dump(FACTS_DIR / f"{ticker}_phase1_facts.json", parsed)
        else:
            collection = collector.collect_ticker(ticker, security_type)
            parsed = parser.parse_ticker(collection)
        current_facts[ticker] = list(parsed.get("facts") or [])
        summary = build_phase1_report(
            ticker=ticker,
            security_type=security_type,
            collection=collection,
            parsed=parsed,
            identity=identity,
        )
        per_ticker[ticker] = {
            "security_type": security_type,
            "identity": identity,
            "collection": collection,
            "parsed_summary": summary,
        }
        all_facts.extend(parsed.get("facts") or [])

    with FACT_STORE_PATH.open("w", encoding="utf-8") as handle:
        for fact in all_facts:
            handle.write(json.dumps(fact) + "\n")

    registry = _write_official_source_registry(tickers)
    audit_rows = _build_fact_status_audit(previous_facts, current_facts)
    _json_dump(FACT_STATUS_AUDIT_PATH, {"generated_at": _utc_now_iso(), "rows": audit_rows})

    run_summary = {
        "generated_at": _utc_now_iso(),
        "tickers": tickers,
        "security_identity_registry_path": str(SECURITY_IDENTITY_REGISTRY_PATH),
        "spcx_identity_path": str(SPCX_IDENTITY_PATH),
        "official_source_registry_path": str(OFFICIAL_SOURCE_REGISTRY_PATH),
        "fact_status_audit_path": str(FACT_STATUS_AUDIT_PATH),
        "per_ticker": {
            t: {
                "security_type": per_ticker[t]["security_type"],
                "identity": per_ticker[t]["identity"],
                "summary": per_ticker[t]["parsed_summary"],
                "official_sources": registry.get(t, []),
            }
            for t in tickers
        },
    }
    _json_dump(RUN_SUMMARY_PATH, run_summary)
    return run_summary


if __name__ == "__main__":
    result = run_phase1(INITIAL_TICKERS)
    print(json.dumps(result, indent=2))
