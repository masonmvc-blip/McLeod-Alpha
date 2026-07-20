"""Inspectable source metrics for the Brain, Memory, and Cockpit boundaries."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_GLOBS = ("control_center.py", "phase3_monitor.py", "execution/**/*.py")
PERSISTENCE_METHODS = {"write_text", "write_bytes", "to_csv", "to_json", "writerow", "writerows"}
POLICY_FUNCTIONS = {"manage_trade", "evaluate_entry", "evaluate_exit", "should_enter", "should_exit"}
COCKPIT_POLICY_PREFIXES = ("_active_stop_", "_classify_exit_", "_indicator_no_entry_", "_validate_runtime_")
MUTATING_SQL_PREFIXES = ("ALTER", "CREATE", "DELETE", "DROP", "INSERT", "REPLACE", "UPDATE")
KNOWN_BASELINES = (
    {
        "id": "live_engine_vwap_snapshot",
        "status": "known",
        "location": "tests/test_phase3_monitor_isolation.py",
        "summary": "Entry diagnostic snapshot does not preserve vwap.",
    },
)
STATUS_POINTS = {"complete": 1.0, "partial": 0.5, "remaining": 0.0}
COMPONENT_WEIGHTS = {"brain": 0.4, "memory": 0.4, "cockpit": 0.2}

# This registry is the architecture review record. Scores are derived only from
# these weighted ownership capabilities, never from AST finding counts.
CAPABILITY_MATRIX = {
    "brain": (
        ("entry_decisions", "Entry decisions", 15, "engine/brain/Brain", "complete", []),
        ("risk_decisions", "Risk decisions", 15, "engine/brain/risk", "complete", []),
        ("trade_management", "Trade management", 20, "engine/brain/Brain", "complete", []),
        ("exit_decisions", "Exit decisions", 20, "engine/brain/Brain", "complete", []),
        ("position_lifecycle", "Position lifecycle", 10, "engine/brain/Brain", "complete", []),
        ("broker_independence", "Broker independence", 20, "engine/brain/Brain", "complete", []),
    ),
    "memory": (
        ("trades", "Trades", 14, "engine/memory/Memory", "complete", ["execution/daily_trade_log_email.py"]),
        ("orders", "Orders", 10, "engine/memory/Memory", "complete", []),
        ("positions", "Positions", 10, "engine/memory/Memory", "complete", []),
        ("signals", "Signals", 8, "engine/memory/Memory", "complete", []),
        ("diagnostics", "Diagnostics", 8, "engine/memory/Memory", "complete", []),
        ("feature_vectors", "Feature vectors", 8, "engine/memory/Memory", "complete", []),
        ("reports", "Reports", 10, "engine/memory/Memory", "complete", []),
        ("performance", "Performance", 8, "engine/memory/Memory", "complete", []),
        ("settings", "Settings", 6, "engine/memory/Memory", "complete", []),
        ("experiments", "CIO evidence and decision journals", 6, "engine/memory/Memory", "complete", []),
        ("optimization_history", "Optimization history", 6, "engine/memory/Memory", "complete", []),
    ),
    "cockpit": (
        ("business_logic", "Business logic", 30, "control_center.py", "partial", ["control_center.py:_active_stop_category", "control_center.py:_classify_exit_reason"]),
        ("direct_persistence", "Direct persistence", 25, "control_center.py", "partial", ["control_center.py"]),
        ("duplicate_runtime_state", "Duplicate runtime state", 20, "control_center.py", "partial", ["control_center.py", "phase3_monitor.py"]),
        ("brain_boundary", "Calls that bypass Brain", 15, "control_center.py", "partial", ["control_center.py"]),
        ("memory_boundary", "Calls that bypass Memory", 10, "control_center.py", "partial", ["control_center.py"]),
    ),
}

EXIT_CRITERIA = {
    "entry_decisions": ("Brain owns entry eligibility, trade planning, startup lifecycle locks, broker-fact admission, quote-quality, and option-contract selection decisions.", "Execution adapters supply broker facts and consume Brain entry instructions without recomputing admission or contract-ranking policy.", "Unit tests cover eligible, rejected, locked, exposure-blocked, quote-blocked, startup-blocked, and option-selection entries."),
    "risk_decisions": ("Risk limits and stop-policy decisions originate in engine/brain.", "Execution does not calculate risk policy.", "Risk decision tests cover loss and stop outcomes."),
    "trade_management": ("All trade-management decisions originate in engine/brain.", "No execution layer computes stop, target, or exit policy.", "The live execution adapter and historical replay consume Brain decisions.", "Unit tests and the simulation/replay adapters cover the management lifecycle."),
    "exit_decisions": ("Brain evaluates automatic and manual exit conditions and canonicalizes exit reasons.", "Execution adapters only submit the requested broker action and report broker outcomes.", "Unit tests cover target, stop, hold-time, manual exit, and reason normalization paths."),
    "position_lifecycle": ("Brain owns lifecycle transitions for protection, exit request, and entry blocking.", "The live execution adapter persists resulting state through Memory and performs broker synchronization.", "Lifecycle tests cover stop recovery and the live execution path."),
    "broker_independence": ("Brain has no broker client imports.", "Brain decisions are serializable broker-neutral instructions."),
    "trades": ("Memory is the sole writer for live trade records.", "Legacy SQLite and report formats are maintained only as Memory projections."),
    "orders": ("Memory records broker order audit state.", "No runtime order writer bypasses Memory."),
    "positions": ("Memory is the sole persistence boundary for open positions.", "Legacy position JSON is maintained only as a projection."),
    "signals": ("Memory records all runtime signal events.", "Legacy signal CSV is maintained only as a projection."),
    "diagnostics": ("Memory records diagnostic snapshots and events.", "Runtime diagnostics have no direct persistent writer."),
    "feature_vectors": ("Memory stores entry feature vectors in a versioned, correlation-keyed schema and emits one append-only event.", "Live feature producers delegate through Memory and retain no direct feature-vector file writer."),
    "reports": ("Memory owns report artifact schemas, event records, and compatibility projections for runtime, daily, delivery, Morning CIO, McLeod launcher, and latency-insights reports.", "All audited report producers use Memory for report persistence and report-source data access."),
    "performance": ("Memory owns daily trade-performance queries, versioned delivery snapshots, and delivery-state projections.", "The daily performance adapter collects broker facts but delegates stored trade performance and state persistence to Memory."),
    "settings": ("Memory owns Cockpit runtime settings, operator actions, compatibility projections, and audit events.", "Cockpit delegates all setting projection reads and writes to Memory."),
    "experiments": ("Memory owns CIO evidence, lineage, decisions, outcomes, and derived journal/chain artifacts as append-only experiment projections.", "CIO evidence-ledger, decision-journal, and evidence-replay producers use Memory for every durable artifact read and write."),
    "optimization_history": ("Memory owns model-weight optimizer inputs, factor-performance history, and weekly recommendations.", "WeightOptimizer uses Memory for every durable CSV and Markdown projection read and write."),
    "business_logic": ("Cockpit presents decisions but does not classify market, trade, or exit policy.", "Business rules are delegated to Brain or a named domain service."),
    "direct_persistence": ("Cockpit writes all persistent state through Memory.", "Cockpit report artifacts are requested through Memory projections."),
    "duplicate_runtime_state": ("Cockpit reads one runtime status model.", "No Cockpit-local copy decides or persists bot lifecycle state."),
    "brain_boundary": ("Cockpit invokes Brain for decision operations.", "No Cockpit path computes or invokes a parallel trading policy."),
    "memory_boundary": ("Cockpit invokes Memory for persistence operations.", "No Cockpit path bypasses Memory for durable state."),
}

PRIORITY_MILESTONES = (
    ("complete_exit_decisions", "Complete canonical exit decisions", "brain", ("exit_decisions",), "engine/brain/engine.py:evaluate_exit"),
    ("consolidate_feature_vectors", "Consolidate feature-vector persistence", "memory", ("feature_vectors",), "execution/live_engine.py"),
    ("remove_cockpit_direct_persistence", "Remove direct Cockpit persistence", "cockpit", ("direct_persistence",), "control_center.py"),
)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _is_write_open(node: ast.Call) -> bool:
    if _call_name(node) != "open":
        return False
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            return any(flag in str(keyword.value.value) for flag in "wax+")
    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
        return any(flag in str(node.args[1].value) for flag in "wax+")
    return False


def _finding(path: Path, line: int, kind: str, detail: str) -> dict[str, Any]:
    return {"path": str(path).replace("\\", "/"), "line": line, "kind": kind, "detail": detail}


def _is_mutating_sql(node: ast.Call) -> bool:
    if _call_name(node) not in {"execute", "executemany", "executescript"} or not node.args:
        return False
    statement = node.args[0]
    if not isinstance(statement, ast.Constant) or not isinstance(statement.value, str):
        return False
    return statement.value.lstrip().upper().startswith(MUTATING_SQL_PREFIXES)


def _scan_file(root: Path, path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    relative = path.relative_to(root)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return [], [], [_finding(relative, 0, "unscannable", type(exc).__name__)]

    persistence: list[dict[str, Any]] = []
    policy: list[dict[str, Any]] = []
    cockpit: list[dict[str, Any]] = []
    is_cockpit = relative.name == "control_center.py"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in PERSISTENCE_METHODS or _is_write_open(node):
                persistence.append(_finding(relative, node.lineno, "direct_write", name or "open"))
            elif _is_mutating_sql(node):
                persistence.append(_finding(relative, node.lineno, "direct_sqlite_write", name))
            elif name == "dump":
                persistence.append(_finding(relative, node.lineno, "direct_json", "json.dump"))

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if relative.parts[:1] == ("execution",) and node.name in POLICY_FUNCTIONS:
                policy.append(_finding(relative, node.lineno, "policy_definition", node.name))
            if is_cockpit and (node.name in POLICY_FUNCTIONS or node.name.startswith(COCKPIT_POLICY_PREFIXES)):
                cockpit.append(_finding(relative, node.lineno, "cockpit_policy", node.name))

    return persistence, policy, cockpit


def _runtime_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for pattern in RUNTIME_GLOBS:
        files.update(root.glob(pattern))
    return sorted(path for path in files if path.is_file() and "__pycache__" not in path.parts)


def _capability_report(component: str) -> dict[str, Any]:
    capabilities = []
    earned_weight = 0.0
    total_weight = 0
    for capability_id, label, weight, owner, status, remaining in CAPABILITY_MATRIX[component]:
        total_weight += weight
        earned_weight += weight * STATUS_POINTS[status]
        capabilities.append({
            "id": capability_id,
            "label": label,
            "weight": weight,
            "owner": owner,
            "status": status,
            "remaining_files": remaining,
            "definition_of_complete": list(EXIT_CRITERIA[capability_id]),
        })
    score = round((earned_weight / total_weight) * 100) if total_weight else 0
    return {"score": score, "capabilities": capabilities}


def _evidence(finding: dict[str, Any], architecture_category: str, why: str) -> dict[str, Any]:
    return {**finding, "category": architecture_category, "why": why}


def _priorities(components: dict[str, dict[str, Any]], overall_score: int) -> dict[str, Any]:
    priorities = []
    for priority_id, label, component_name, capability_ids, blocker in PRIORITY_MILESTONES:
        capabilities = {item["id"]: item for item in components[component_name]["capabilities"]}
        pending_targets = [capability_id for capability_id in capability_ids if capabilities[capability_id]["status"] != "complete"]
        if not pending_targets:
            continue
        impact = sum(
            item["weight"] * (1.0 - STATUS_POINTS[item["status"]]) * COMPONENT_WEIGHTS[component_name]
            for capability_id in pending_targets
            if (item := capabilities[capability_id])
        )
        impact_percent = round(impact)
        priorities.append({
            "id": priority_id,
            "label": label,
            "blocker": blocker,
            "targets": list(capability_ids),
            "impact_percent": impact_percent,
        })
    next_impact = priorities[0]["impact_percent"] if priorities else 0
    return {"priorities": priorities, "estimated_completion_after_next_milestone": min(100, overall_score + next_impact)}


def build_architecture_health(root: Path | str | None = None) -> dict[str, Any]:
    """Return a stable, source-derived consolidation report for the live runtime."""
    repository = Path(root or PROJECT_ROOT).resolve()
    persistence: list[dict[str, Any]] = []
    policy: list[dict[str, Any]] = []
    cockpit_policy: list[dict[str, Any]] = []
    scanner_issues: list[dict[str, Any]] = []
    files = _runtime_files(repository)

    for path in files:
        found_persistence, found_policy, found_cockpit = _scan_file(repository, path)
        persistence.extend(found_persistence)
        policy.extend(found_policy)
        cockpit_policy.extend(found_cockpit)

    brain = _capability_report("brain")
    memory = _capability_report("memory")
    cockpit = _capability_report("cockpit")
    brain["evidence"] = [_evidence(item, "decision_outside_brain", "Trading-policy definition remains outside the canonical Brain package.") for item in policy]
    memory["evidence"] = [_evidence(item, "direct_writer_outside_memory", "Runtime persistence bypasses the canonical Memory service.") for item in persistence]
    cockpit["evidence"] = [
        *[_evidence(item, "business_logic_in_cockpit", "Cockpit contains a candidate business-rule implementation.") for item in cockpit_policy],
        *[_evidence(item, "direct_persistence_in_cockpit", "Cockpit writes state directly instead of using Memory.") for item in persistence if item["path"] == "control_center.py"],
    ]
    components = {"brain": brain, "memory": memory, "cockpit": cockpit}
    overall_score = round(sum(components[name]["score"] * weight for name, weight in COMPONENT_WEIGHTS.items()))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "files_scanned": [str(path.relative_to(repository)).replace("\\", "/") for path in files],
            "exclusions": ["engine/memory/**", "tests/**", "research/backtesting/report artifacts"],
        },
        "rules": {
            "direct_persistence": "AST calls to mutating SQL, json.dump, write methods, CSV writers, or writable open outside Memory; read-only SQLite connections are excluded.",
            "brain_policy": "Execution functions named manage_trade/evaluate_entry/evaluate_exit/should_enter/should_exit outside engine/brain.",
            "cockpit_policy": "Control Center functions that classify exits, stops, entry reasons, or runtime validation.",
            "score": "Scores come only from the reviewed capability matrix: Complete=100% of its weight, Partial=50%, Remaining=0%. AST findings are evidence and never modify scores.",
            "completion": "Every capability lists its definition of complete. A status may change only after each criterion is demonstrably satisfied.",
        },
        "brain": brain,
        "memory": memory,
        "cockpit": cockpit,
        "priorities": _priorities(components, overall_score),
        "baseline": {"known_issues": list(KNOWN_BASELINES), "scanner_issues": scanner_issues},
        "overall": {"score": overall_score, "completion_percent": overall_score},
    }