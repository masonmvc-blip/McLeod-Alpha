#!/usr/bin/env python3
"""Maintain the DayTradeSPY research roadmap, ranked backlog, and debt registers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .daytradespy_research_registry import GOVERNANCE_DECISION
else:
    from daytradespy_research_registry import GOVERNANCE_DECISION


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def priority_score(item: dict[str, Any]) -> float:
    """Score portfolio value by impact, uncertainty reduction, readiness, and cost."""
    if item.get("status") == "BLOCKED_EXTERNAL":
        return 0.0
    value = item["expected_alpha_impact"] * item["confidence"] * item["probability_of_success"]
    readiness = (item["data_readiness"] + item["replay_readiness"] + item["governance_readiness"]) / 3
    cost = item["engineering_cost"] + item["research_cost"]
    return round((value * readiness * (1 + item["expected_research_uncertainty_reduction_pct"] / 100)) / max(cost, 1), 2)


def _attach_economic_estimate(task: dict[str, Any]) -> None:
    """Attach required ROI fields to every task before it can enter the portfolio."""
    estimates = {
        "DTS-ROADMAP-001": ("High", 55, ["DTS-ROADMAP-003", "exit-quality research", "slippage counterfactuals"], ["range-congestion re-entry", "stop-policy evaluation"], "5 engineering days", 0.75, "Medium"),
        "DTS-ROADMAP-002": ("High", 35, ["chart-structure verification", "no-trade review"], ["source-claim validation"], "2 engineering days", 0.65, "Medium"),
        "DTS-ROADMAP-003": ("Medium", 20, ["hypothesis lifecycle decision"], ["range-congestion re-entry"], "3 research days", 0.45, "High"),
        "DTS-ROADMAP-004": ("Low", 5, ["replication sample growth"], [], "8 research days per archive tranche", 0.55, "High"),
    }
    alpha, uncertainty, unblocked, replays, effort, success, failure = estimates[task["id"]]
    task.update({
        "estimated_alpha_unlocked": alpha,
        "expected_research_uncertainty_reduction_pct": uncertainty,
        "downstream_tasks_unblocked": unblocked,
        "replay_programs_accelerated": replays,
        "engineering_effort": effort,
        "probability_of_success": success,
        "risk_of_failure": failure,
        "portfolio_falsification": "Archive breadth is not the highest-value task while option telemetry and visual verification remain incomplete." if task["id"] == "DTS-ROADMAP-004" else "No higher-value portfolio bottleneck was identified after comparing data quality, reuse across experiments, and replay leverage.",
        "roi_success_measure": task["success_measure"],
        "roi_closure_question": "Did this measurably improve research quality, reproducibility, governance, future engineering leverage, or risk-adjusted replay performance?",
    })


def _append_priority_decision(root: Path, previous: str, current: str) -> None:
    """Append, never rewrite, the evidence behind a portfolio-priority change."""
    journal = root / "decision_journal.jsonl"
    if journal.exists() and previous == current:
        return
    details = {
        "DTS-ROADMAP-001": (
            "Option quote, excursion, ledger, and Greeks evidence remains unavailable across reviewed recordings.",
            "More recording coverage alone is the fastest path to actionable research learning.",
            "Research-grade telemetry is reusable across every future replay and converts qualitative claims into falsifiable outcome evidence.",
            "High alpha-unlocking leverage; estimated 55% reduction in research uncertainty once telemetry coverage reaches the stated success measure.",
        ),
        "DTS-ROADMAP-002": (
            "Authorized browser playback and transcript controls work; the remaining constraint is completing a structured visual-review pilot, not restoring source access.",
            "Visual review access is externally blocked and cannot currently earn research value.",
            "A bounded pilot has low engineering cost, verifies chart and no-trade evidence, and improves the quality of every subsequent source review.",
            "High research-quality leverage; estimated 35% reduction in source-review uncertainty if the pilot reaches full visual coverage.",
        ),
    }
    evidence, falsified, why_better, impact = details[current]
    entry = {
        "date": datetime.now(timezone.utc).isoformat(),
        "previous_priority": previous,
        "new_priority": current,
        "evidence": evidence,
        "falsified_assumption": falsified,
        "why_higher_expected_value": why_better,
        "expected_impact": impact,
        "confidence": "HIGH",
    }
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def build_control_plane(root: Path) -> dict[str, dict[str, Any]]:
    registry = _read(root / "recording_registry.json")
    hypotheses = _read(root / "hypothesis_registry.json")["hypotheses"]
    incomplete = sum(item["analysis_status"] != "complete" for item in registry["recordings"])
    access_status = _read(root / "visual_review_access.json") if (root / "visual_review_access.json").exists() else {}
    tasks = [
        {
            "id": "DTS-ROADMAP-001", "title": "Capture research-grade option excursion telemetry", "expected_alpha_impact": 95,
            "confidence": 0.9, "engineering_cost": 5, "research_cost": 2, "data_readiness": 0.25,
            "replay_readiness": 0.2, "governance_readiness": 1.0, "estimated_time": "3-5 engineering days",
            "why_better": "It converts exit, stop, spread, MFE, and MAE assertions into testable outcomes across every future replay.",
            "success_measure": "At least 95% of new research trades contain bid, ask, mark, MFE, MAE, extrema timestamps, and Greeks.",
            "falsifier": "Replay conclusions remain unchanged after complete telemetry is available.",
        },
        {
            "id": "DTS-ROADMAP-002", "title": "Run a research-grade visual-review pilot", "expected_alpha_impact": 80,
            "confidence": 0.85, "engineering_cost": 2, "research_cost": 2, "data_readiness": 0.2,
            "replay_readiness": 0.35, "governance_readiness": 1.0, "estimated_time": "1-2 days",
            "why_better": "Transcript-only evidence cannot validate chart structure, option-chain context, or no-trade decisions.",
            "success_measure": "Visual coverage reaches 100% for a pilot recording without storing video.",
            "falsifier": "Visual review produces no material additions or corrections to transcript-only records.",
            "status": access_status.get("status", "READY"),
            "blocker": access_status.get("blocker", "NONE"),
        },
        {
            "id": "DTS-ROADMAP-003", "title": "Replay range-congestion re-entry throttle", "expected_alpha_impact": 70,
            "confidence": 0.45, "engineering_cost": 3, "research_cost": 4, "data_readiness": 0.45,
            "replay_readiness": 0.3, "governance_readiness": 1.0, "estimated_time": "2-3 research days after telemetry",
            "why_better": "It tests the only structured source hypothesis against McLeod Alpha's baseline rather than imitating the presenter.",
            "success_measure": "Out-of-sample risk-adjusted expectancy improves with no unacceptable missed-opportunity cost.",
            "falsifier": "Negative controls or out-of-sample replay show no improvement or worse risk-adjusted outcomes.",
            "hypothesis_id": hypotheses[0]["id"] if hypotheses else "NONE",
        },
        {
            "id": "DTS-ROADMAP-004", "title": "Expand archive review", "expected_alpha_impact": 25,
            "confidence": 0.5, "engineering_cost": 3, "research_cost": 8, "data_readiness": 0.1,
            "replay_readiness": 0.1, "governance_readiness": 1.0, "estimated_time": f"{incomplete} recordings pending",
            "why_better": "Breadth can increase replication coverage after evidence quality is sufficient.",
            "success_measure": "Completed records have full transcript and visual coverage with reproducible outcomes.",
            "falsifier": "New completed records fail to change confidence, recurrence, or replay priority.",
        },
    ]
    for task in tasks:
        _attach_economic_estimate(task)
        task["priority_score"] = priority_score(task)
    tasks.sort(key=lambda item: item["priority_score"], reverse=True)
    highest_value_task = tasks[0]["id"]
    roadmap = {
        "schema_version": "daytradespy-research-roadmap.v1", "updated_at": datetime.now(timezone.utc).isoformat(),
        "governance_decision": GOVERNANCE_DECISION, "current_research_maturity_pct": 25,
        "biggest_bottleneck": "No research-grade option excursion telemetry and no completed visual review.",
        "biggest_missing_dataset": "Timestamped option bid/ask/mark, MFE/MAE, extrema, and Greeks tied to trades.",
        "highest_expected_value_experiment": "DTS-ROADMAP-003", "highest_engineering_roi": highest_value_task,
        "highest_research_roi": highest_value_task, "biggest_technical_debt": "No automated, authenticated visual-review acquisition path.",
        "biggest_research_debt": f"{incomplete} recordings lack complete evidence coverage.",
        "biggest_governance_risk": "Treating transcript-only/source-reported results as proof of incremental alpha.",
        "ranking_rule": "Expected alpha impact, confidence, probability of success, and uncertainty reduction, adjusted for data/replay/governance readiness and total cost.",
        "portfolio_challenge": "Archive expansion is deprioritized until its marginal learning value exceeds the reusable value of telemetry and visual verification.",
        "tasks": tasks,
    }
    technical_debt = {"schema_version": "daytradespy-technical-debt.v1", "items": [
        {"id": "DTS-TECH-001", "severity": "HIGH", "issue": "No automated visual review acquisition path.", "remediation": "Use authorized source access to extract reviewable captions/frame references without persisting video.", "status": "OPEN"},
        {"id": "DTS-TECH-002", "severity": "MEDIUM", "issue": "No pytest environment is installed.", "remediation": "Provision a pinned test environment and convert smoke assertions into focused tests.", "status": "OPEN"},
        {"id": "DTS-TECH-003", "severity": "RESOLVED", "issue": "Archive records required manual discovery and could not be searched uniformly.", "remediation": "Local SQLite FTS catalog refreshes with daily ingestion.", "status": "RESOLVED"},
        {"id": "DTS-TECH-004", "severity": "RESOLVED", "issue": "No standardized safe import path existed for authorized transcript exports.", "remediation": "VTT importer preserves timestamped cues and provenance without retaining video, cookies, tokens, or signed URLs.", "status": "RESOLVED"},
        {"id": "DTS-TECH-005", "severity": "RESOLVED", "issue": "Existing DayTradeSPY reports were disconnected from the research registry and full-text catalog.", "remediation": "Registry classifies matching daily reports as legacy evidence and catalog indexes their text.", "status": "RESOLVED"},
        {"id": "DTS-TECH-006", "severity": "RESOLVED", "issue": "Available 2026 DayTradeSPY daily reports used inconsistent prose-only formats.", "remediation": "All matched 2026 reports are converted into full-schema records, standardized output bundles, claims, and full-text search documents.", "status": "RESOLVED"},
    ]}
    research_debt = {"schema_version": "daytradespy-research-debt.v1", "items": [
        {"id": "DTS-RESEARCH-001", "severity": "P0", "issue": "Option excursion and quote telemetry unavailable.", "blocks": ["exit-quality conclusions", "spread/slippage counterfactuals", "MFE/MAE comparison"], "status": "OPEN"},
        {"id": "DTS-RESEARCH-002", "severity": "P0", "issue": "No recording has completed visual coverage.", "blocks": ["chart-structure verification", "option-chain evidence", "complete review status"], "status": "OPEN"},
        {"id": "DTS-RESEARCH-003", "severity": "HIGH", "issue": "Range re-entry hypothesis has no replay evidence.", "blocks": ["hypothesis lifecycle advancement"], "status": "OPEN"},
    ]}
    return {"research_roadmap.json": roadmap, "research_backlog.json": {"schema_version": "daytradespy-research-backlog.v1", "tasks": tasks}, "technical_debt_register.json": technical_debt, "research_debt_register.json": research_debt}


def refresh(root: Path) -> dict[str, dict[str, Any]]:
    prior_path = root / "research_roadmap.json"
    prior = _read(prior_path) if prior_path.exists() else {}
    artifacts = build_control_plane(root)
    for name, content in artifacts.items():
        _write(root / name, content)
    _append_priority_decision(root, prior.get("highest_engineering_roi", "NO_DECISION_JOURNAL"), artifacts["research_roadmap.json"]["highest_engineering_roi"])
    return artifacts


if __name__ == "__main__":
    root = Path("data/research/daytradespy")
    refresh(root)
    print("DayTradeSPY research director control plane refreshed")