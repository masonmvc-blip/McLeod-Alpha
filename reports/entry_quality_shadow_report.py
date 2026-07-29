"""Canonical, research-only studies for Phase/CQ/MAS/ABS/CONF."""

from __future__ import annotations

import csv
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
STUDY_VERSION = "entry-quality-shadow.v2"
FRESH_START_DATE = "2026-07-29"
MINIMUM_GROUP_SAMPLE = 20
CHECKLIST_SCORES = (5, 6, 7)
STANDARD_PHASES = {
    "INITIATION",
    "EARLY_CONTINUATION",
    "ESTABLISHED",
    "MATURE",
    "LATE_EXHAUSTION",
}


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return _object(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _diagnostic_values(row: sqlite3.Row) -> dict[str, Any]:
    payload = _object(row["feature_payload"])
    stage = payload.get("trend_stage") or {}
    checklist = payload.get("checklist") if isinstance(payload.get("checklist"), dict) else {}
    indicator_labels: list[str] = []
    for candidate in (
        checklist.get("entry_reasons"),
        payload.get("entry_reasons"),
        payload.get("entry_reasons_call"),
        payload.get("entry_reasons_put"),
    ):
        if not isinstance(candidate, list):
            continue
        for value in candidate:
            label = str(value or "").strip()
            if label and label not in indicator_labels:
                indicator_labels.append(label)
    return {
        "phase": (
            payload.get("momentum_phase")
            or row["momentum_phase"]
            or (stage.get("label") if isinstance(stage, dict) else None)
        ),
        "cq": _number(
            payload.get("continuation_quality_score")
            if payload.get("continuation_quality_score") is not None
            else (payload.get("continuation_quality") or {}).get("score")
        ),
        "mas": _number(
            payload.get("momentum_acceleration_score")
            if payload.get("momentum_acceleration_score") is not None
            else (payload.get("momentum_acceleration") or {}).get("score")
        ),
        "abs": _number(
            payload.get("absorption_score")
            if payload.get("absorption_score") is not None
            else (
                (payload.get("absorption") or {}).get("score")
                if payload.get("absorption")
                else row["absorption_score"]
            )
        ),
        "conf": _number(
            payload.get("confidence_score")
            if payload.get("confidence_score") is not None
            else (payload.get("confidence") or {}).get("score")
        ),
        "checklist_score": _number(
            payload.get("entry_score")
            if payload.get("entry_score") is not None
            else (
                checklist.get("entry_score")
                if checklist.get("entry_score") is not None
                else checklist.get("passed")
            )
        ),
        "indicator_labels": indicator_labels,
    }


def _load_best_diagnostics(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, broker_entry_order_id, momentum_phase,
               absorption_score, feature_payload
        FROM trade_log
        WHERE trim(COALESCE(broker_entry_order_id, '')) <> ''
        ORDER BY id
        """
    ).fetchall()
    selected: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for row in rows:
        values = _diagnostic_values(row)
        coverage = sum(
            value is not None and (not isinstance(value, list) or bool(value))
            for value in values.values()
        )
        order_id = str(row["broker_entry_order_id"] or "")
        candidate = (coverage, int(row["id"]), values)
        if order_id not in selected or candidate[:2] > selected[order_id][:2]:
            selected[order_id] = candidate
    return {order_id: candidate[2] for order_id, candidate in selected.items()}


def _load_latest_canonical_payloads(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT canonical_trade_id, canonical_version, payload
        FROM canonical_completed_trade_versions
        ORDER BY canonical_trade_id, canonical_version
        """
    ).fetchall()
    selected: dict[str, dict[str, Any]] = {}
    for canonical_trade_id, canonical_version, raw_payload in rows:
        payload = _object(raw_payload)
        current = selected.get(str(canonical_trade_id))
        broker_cash = str(payload.get("pnl_source") or "").lower() == "broker_cash"
        current_broker_cash = bool(
            current and str(current.get("pnl_source") or "").lower() == "broker_cash"
        )
        if (
            current is None
            or (broker_cash and not current_broker_cash)
            or (
                broker_cash == current_broker_cash
                and int(canonical_version) > int(current.get("canonical_version") or 0)
            )
        ):
            payload["canonical_trade_id"] = str(canonical_trade_id)
            payload["canonical_version"] = int(canonical_version)
            selected[str(canonical_trade_id)] = payload
    return list(selected.values())


def load_study_trades(*, root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return one economic trade per broker entry order plus coverage facts."""
    db_path = root / "data" / "mcleod_alpha.db"
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        diagnostics = _load_best_diagnostics(connection)
        canonical = _load_latest_canonical_payloads(connection)

    representations: list[dict[str, Any]] = []
    for payload in canonical:
        entry_order_id = str(payload.get("broker_entry_order_id") or "")
        if not all(
            (
                entry_order_id,
                str(payload.get("broker_exit_order_id") or ""),
                str(payload.get("option_symbol") or ""),
            )
        ):
            continue
        entry_time = str(payload.get("entry_time") or "")
        values = diagnostics.get(entry_order_id, {})
        representations.append(
            {
                "canonical_trade_id": payload.get("canonical_trade_id"),
                "broker_entry_order_id": entry_order_id,
                "broker_exit_order_id": str(payload.get("broker_exit_order_id") or ""),
                "trade_date": entry_time[:10],
                "entry_time": entry_time,
                "direction": str(payload.get("direction") or "UNKNOWN").upper(),
                "pnl_dollars": round(
                    _number(payload.get("option_pnl_dollars"))
                    or _number(payload.get("pnl"))
                    or 0.0,
                    2,
                ),
                "exit_reason": str(payload.get("exit_reason") or "UNKNOWN"),
                "source": str(payload.get("source") or ""),
                **values,
            }
        )

    # Historical local-close and broker-reconciled representations can share
    # one broker entry order. Prefer the actual broker-reconciled outcome.
    deduplicated: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for trade in representations:
        preference = (
            trade["exit_reason"] == "BROKER_RECONCILED_EXIT",
            trade["source"] == "cockpit_health_reconciliation",
            str(trade["canonical_trade_id"]),
        )
        order_id = trade["broker_entry_order_id"]
        if order_id not in deduplicated or preference > deduplicated[order_id][0]:
            deduplicated[order_id] = (preference, trade)
    trades = sorted(
        (item[1] for item in deduplicated.values()),
        key=lambda trade: (trade["entry_time"], trade["broker_entry_order_id"]),
    )
    coverage = {
        "canonical_representations": len(representations),
        "distinct_broker_entries": len(trades),
        "phase_cq_mas_conf": sum(
            all(trade.get(key) is not None for key in ("phase", "cq", "mas", "conf"))
            for trade in trades
        ),
        "complete_five_metrics": sum(
            all(trade.get(key) is not None for key in ("phase", "cq", "mas", "abs", "conf"))
            for trade in trades
        ),
        "standard_phase_complete": sum(
            all(trade.get(key) is not None for key in ("cq", "mas", "abs", "conf"))
            and trade.get("phase") in STANDARD_PHASES
            for trade in trades
        ),
        "checklist_score": sum(trade.get("checklist_score") is not None for trade in trades),
        "indicator_labels": sum(bool(trade.get("indicator_labels")) for trade in trades),
    }
    return trades, coverage


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(row.get("pnl_dollars") or 0.0) for row in rows]
    wins = sum(pnl > 0 for pnl in pnls)
    directions = {
        "CALL": sum(str(row.get("direction")) == "CALL" for row in rows),
        "PUT": sum(str(row.get("direction")) == "PUT" for row in rows),
    }
    return {
        "trades": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "win_rate": round(wins / len(rows), 4) if rows else None,
        "pnl_dollars": round(sum(pnls), 2),
        "average_pnl_dollars": round(sum(pnls) / len(rows), 2) if rows else None,
        "median_pnl_dollars": round(median(pnls), 2) if rows else None,
        "directions": directions,
    }


def _cohorts(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "early_continuation_conf_4_candidate": [
            row for row in rows
            if row.get("phase") == "EARLY_CONTINUATION" and float(row.get("conf") or 0) >= 4.0
        ],
        "all_other_complete_comparator": [
            row for row in rows
            if not (
                row.get("phase") == "EARLY_CONTINUATION"
                and float(row.get("conf") or 0) >= 4.0
            )
        ],
        "established_call_shadow_reject": [
            row for row in rows
            if row.get("phase") == "ESTABLISHED" and row.get("direction") == "CALL"
        ],
        "non_established_call_comparator": [
            row for row in rows
            if row.get("phase") != "ESTABLISHED" and row.get("direction") == "CALL"
        ],
        "established_put_shadow_reject": [
            row for row in rows
            if row.get("phase") == "ESTABLISHED" and row.get("direction") == "PUT"
        ],
        "non_established_put_comparator": [
            row for row in rows
            if row.get("phase") != "ESTABLISHED" and row.get("direction") == "PUT"
        ],
    }


def _score_tables(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        row for row in rows
        if _number(row.get("checklist_score")) is not None
    ]

    def by_score(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            str(score): _stats([
                row for row in group
                if int(float(row.get("checklist_score") or 0)) == score
            ])
            for score in CHECKLIST_SCORES
        }

    direction_phase: dict[str, dict[str, Any]] = {}
    for direction in ("CALL", "PUT"):
        direction_rows = [row for row in scored if row.get("direction") == direction]
        direction_phase[direction] = {
            "all_phases": by_score(direction_rows),
            "by_phase": {
                phase: by_score([
                    row for row in direction_rows if row.get("phase") == phase
                ])
                for phase in sorted(STANDARD_PHASES)
            },
        }
    return {
        "covered_trades": len(scored),
        "overall": by_score(scored),
        "by_direction_and_phase": direction_phase,
    }


def _indicator_present(row: dict[str, Any], indicator: str) -> bool:
    return indicator in (row.get("indicator_labels") or [])


def _phase_count(rows: list[dict[str, Any]]) -> int:
    return len({
        row.get("phase") for row in rows
        if row.get("phase") in STANDARD_PHASES
    })


def _weight_hypothesis(
    rows: list[dict[str, Any]],
    *,
    direction: str,
    indicator: str,
) -> dict[str, Any]:
    universe = [row for row in rows if row.get("direction") == direction]
    present = [row for row in universe if _indicator_present(row, indicator)]
    absent = [row for row in universe if not _indicator_present(row, indicator)]
    return {
        "direction": direction,
        "indicator": indicator,
        "present": _stats(present),
        "absent_same_direction": _stats(absent),
        "phase_breakdown": {
            phase: {
                "present": _stats([
                    row for row in present if row.get("phase") == phase
                ]),
                "absent_same_direction": _stats([
                    row for row in absent if row.get("phase") == phase
                ]),
            }
            for phase in sorted(STANDARD_PHASES)
        },
        "phase_counts": {
            "present": _phase_count(present),
            "absent_same_direction": _phase_count(absent),
        },
    }


def _indicator_weight_study(
    historical_rows: list[dict[str, Any]],
    fresh_rows: list[dict[str, Any]],
    *,
    reconciliation_complete: bool,
    collection_started: bool,
) -> dict[str, Any]:
    definitions = {
        "call_breaks_previous_high": ("CALL", "breaks_prev_high", "INCREASE"),
        "call_macd_improving": ("CALL", "macd_improving", "INCREASE"),
        "put_bearish_volume_bonus": (
            "PUT",
            "volume_confirming_bearish_move",
            "REMOVE_OR_REDUCE",
        ),
    }
    hypotheses: dict[str, Any] = {}
    for name, (direction, indicator, proposed_action) in definitions.items():
        historical = _weight_hypothesis(
            historical_rows,
            direction=direction,
            indicator=indicator,
        )
        fresh = _weight_hypothesis(
            fresh_rows,
            direction=direction,
            indicator=indicator,
        )
        checks = {
            "fresh_collection_started": collection_started,
            "canonical_reconciliation_complete": reconciliation_complete,
            "present_minimum_20": fresh["present"]["trades"] >= MINIMUM_GROUP_SAMPLE,
            "absent_same_direction_minimum_20": (
                fresh["absent_same_direction"]["trades"] >= MINIMUM_GROUP_SAMPLE
            ),
            "present_has_two_phases": fresh["phase_counts"]["present"] >= 2,
            "absent_has_two_phases": fresh["phase_counts"]["absent_same_direction"] >= 2,
        }
        ready = all(checks.values())
        hypotheses[name] = {
            "proposed_action": proposed_action,
            "historical": historical,
            "fresh": fresh,
            "checks": checks,
            "ready_for_human_review": ready,
            "decision": "ELIGIBLE_FOR_HUMAN_REVIEW" if ready else "COLLECT_MORE_DATA",
        }
    return hypotheses


def _score_study_checks(
    score_tables: dict[str, Any],
    *,
    reconciliation_complete: bool,
    collection_started: bool,
) -> dict[str, bool]:
    checks = {
        "fresh_collection_started": collection_started,
        "canonical_reconciliation_complete": reconciliation_complete,
    }
    for direction in ("CALL", "PUT"):
        direction_rows = score_tables["by_direction_and_phase"][direction]
        for score in CHECKLIST_SCORES:
            stats = direction_rows["all_phases"][str(score)]
            phases_with_trades = sum(
                direction_rows["by_phase"][phase][str(score)]["trades"] > 0
                for phase in STANDARD_PHASES
            )
            checks[f"{direction.lower()}_score_{score}_minimum_20"] = (
                stats["trades"] >= MINIMUM_GROUP_SAMPLE
            )
            checks[f"{direction.lower()}_score_{score}_has_two_phases"] = (
                phases_with_trades >= 2
            )
    return checks


def canonical_indicator_performance(
    trades: list[dict[str, Any]],
    *,
    trading_date: str,
    minimum_sample_size: int = MINIMUM_GROUP_SAMPLE,
) -> list[dict[str, Any]]:
    """Compare each indicator with its same-direction absent comparator."""
    indicators = sorted({
        label
        for trade in trades
        for label in (trade.get("indicator_labels") or [])
    })
    rows: list[dict[str, Any]] = []
    for indicator in indicators:
        present_all = [trade for trade in trades if _indicator_present(trade, indicator)]
        direction_counts = {
            direction: sum(trade.get("direction") == direction for trade in present_all)
            for direction in ("CALL", "PUT")
        }
        direction = max(direction_counts, key=direction_counts.get)
        universe = [trade for trade in trades if trade.get("direction") == direction]
        present = [trade for trade in universe if _indicator_present(trade, indicator)]
        absent = [trade for trade in universe if not _indicator_present(trade, indicator)]
        present_stats = _stats(present)
        absent_stats = _stats(absent)
        today = [
            trade for trade in present
            if str(trade.get("trade_date") or "") == trading_date
        ]
        today_stats = _stats(today)

        if len(present) < minimum_sample_size or len(absent) < minimum_sample_size:
            guidance = "Collect canonical comparators"
        else:
            present_rate = float(present_stats.get("win_rate") or 0.0)
            absent_rate = float(absent_stats.get("win_rate") or 0.0)
            present_average = float(present_stats.get("average_pnl_dollars") or 0.0)
            absent_average = float(absent_stats.get("average_pnl_dollars") or 0.0)
            if present_rate >= absent_rate + 0.10 and present_average >= absent_average + 10:
                guidance = "Shadow increase candidate"
            elif present_rate <= absent_rate - 0.10 and present_average <= absent_average - 10:
                guidance = "Shadow reduction candidate"
            else:
                guidance = "Keep shadowing"
        rows.append({
            "indicator": indicator,
            "direction": direction,
            "trades": present_stats["trades"],
            "wins": present_stats["wins"],
            "losses": present_stats["losses"],
            "breakeven": present_stats["trades"] - present_stats["wins"] - present_stats["losses"],
            "win_rate_pct": round(float(present_stats.get("win_rate") or 0.0) * 100, 1),
            "average_return": present_stats["average_pnl_dollars"] or 0.0,
            "absent_trades": absent_stats["trades"],
            "absent_wins": absent_stats["wins"],
            "absent_losses": absent_stats["losses"],
            "absent_win_rate_pct": round(float(absent_stats.get("win_rate") or 0.0) * 100, 1),
            "absent_average_return": absent_stats["average_pnl_dollars"] or 0.0,
            "today_trades": today_stats["trades"],
            "today_wins": today_stats["wins"],
            "today_losses": today_stats["losses"],
            "today_breakeven": (
                today_stats["trades"] - today_stats["wins"] - today_stats["losses"]
            ),
            "guidance": guidance,
            "canonical": True,
            "automatic_live_change_allowed": False,
        })
    return sorted(
        rows,
        key=lambda row: (
            row["guidance"] not in {
                "Shadow increase candidate",
                "Shadow reduction candidate",
            },
            -row["trades"],
            row["indicator"],
        ),
    )


def evaluate_entry_quality_shadow(
    trades: list[dict[str, Any]],
    *,
    trading_date: str,
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    bounded_trades = [
        trade for trade in trades
        if str(trade.get("trade_date") or "") <= trading_date
    ]
    comparable = [
        trade for trade in bounded_trades
        if trade.get("phase") in STANDARD_PHASES
        and all(trade.get(key) is not None for key in ("cq", "mas", "abs", "conf"))
    ]
    historical = _cohorts(comparable)
    fresh_rows = [
        trade for trade in comparable
        if FRESH_START_DATE <= str(trade.get("trade_date") or "") <= trading_date
    ]
    fresh = _cohorts(fresh_rows)
    historical_stats = {name: _stats(rows) for name, rows in historical.items()}
    fresh_stats = {name: _stats(rows) for name, rows in fresh.items()}

    primary_candidate = fresh_stats["early_continuation_conf_4_candidate"]
    primary_comparator = fresh_stats["all_other_complete_comparator"]
    primary_checks = {
        "candidate_minimum_20": primary_candidate["trades"] >= MINIMUM_GROUP_SAMPLE,
        "comparator_minimum_20": primary_comparator["trades"] >= MINIMUM_GROUP_SAMPLE,
        "candidate_has_call_and_put": all(
            primary_candidate["directions"].get(direction, 0) > 0
            for direction in ("CALL", "PUT")
        ),
        "comparator_has_call_and_put": all(
            primary_comparator["directions"].get(direction, 0) > 0
            for direction in ("CALL", "PUT")
        ),
    }
    established_groups = (
        "established_call_shadow_reject",
        "non_established_call_comparator",
        "established_put_shadow_reject",
        "non_established_put_comparator",
    )
    established_checks = {
        f"{name}_minimum_20": fresh_stats[name]["trades"] >= MINIMUM_GROUP_SAMPLE
        for name in established_groups
    }
    common_checks = {
        "fresh_collection_started": trading_date >= FRESH_START_DATE,
        "canonical_reconciliation_complete": bool(reconciliation.get("complete")),
    }
    score_historical = _score_tables(bounded_trades)
    score_fresh_rows = [
        trade for trade in bounded_trades
        if FRESH_START_DATE <= str(trade.get("trade_date") or "") <= trading_date
    ]
    score_fresh = _score_tables(score_fresh_rows)
    score_checks = _score_study_checks(
        score_fresh,
        reconciliation_complete=bool(reconciliation.get("complete")),
        collection_started=trading_date >= FRESH_START_DATE,
    )
    score_ready = all(score_checks.values())
    indicator_hypotheses = _indicator_weight_study(
        bounded_trades,
        score_fresh_rows,
        reconciliation_complete=bool(reconciliation.get("complete")),
        collection_started=trading_date >= FRESH_START_DATE,
    )
    primary_ready = all({**common_checks, **primary_checks}.values())
    established_ready = all({**common_checks, **established_checks}.values())
    return {
        "schema_version": STUDY_VERSION,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "fresh_start_date": FRESH_START_DATE,
        "trading_date": trading_date,
        "historical_comparable_trades": len(comparable),
        "fresh_comparable_trades": len(fresh_rows),
        "today_trades": [
            trade for trade in comparable if trade.get("trade_date") == trading_date
        ],
        "historical_cohorts": historical_stats,
        "fresh_cohorts": fresh_stats,
        "checklist_score_study": {
            "score_semantics": (
                "Weighted points: five base conditions, EMA stack is worth two "
                "points, and volume can add or subtract one."
            ),
            "historical": score_historical,
            "fresh": score_fresh,
            "checks": score_checks,
            "ready_for_human_review": score_ready,
            "decision": (
                "ELIGIBLE_FOR_HUMAN_REVIEW" if score_ready else "COLLECT_MORE_DATA"
            ),
        },
        "indicator_weight_study": {
            "hypotheses": indicator_hypotheses,
            "minimum_present_and_absent_sample": MINIMUM_GROUP_SAMPLE,
            "phase_control_required": True,
        },
        "hypotheses": {
            "early_continuation_conf_4": {
                "candidate": "early_continuation_conf_4_candidate",
                "comparator": "all_other_complete_comparator",
                "checks": {**common_checks, **primary_checks},
                "ready_for_human_review": primary_ready,
                "decision": "ELIGIBLE_FOR_HUMAN_REVIEW" if primary_ready else "COLLECT_MORE_DATA",
            },
            "established_shadow_reject_by_direction": {
                "checks": {**common_checks, **established_checks},
                "ready_for_human_review": established_ready,
                "decision": "ELIGIBLE_FOR_HUMAN_REVIEW" if established_ready else "COLLECT_MORE_DATA",
            },
            "checklist_scores_5_6_7_by_direction_and_phase": {
                "checks": score_checks,
                "ready_for_human_review": score_ready,
                "decision": (
                    "ELIGIBLE_FOR_HUMAN_REVIEW"
                    if score_ready
                    else "COLLECT_MORE_DATA"
                ),
            },
            **{
                f"indicator_weight_{name}": {
                    "checks": hypothesis["checks"],
                    "ready_for_human_review": hypothesis["ready_for_human_review"],
                    "decision": hypothesis["decision"],
                }
                for name, hypothesis in indicator_hypotheses.items()
            },
        },
        "reconciliation": reconciliation,
        "conclusions_withheld": not bool(reconciliation.get("complete")),
    }


def render_entry_quality_shadow_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## Entry Quality Shadow Studies",
        "",
        f"- Study: `{payload.get('schema_version')}`; fresh collection begins "
        f"**{payload.get('fresh_start_date')}**.",
        "- Research only: these cohorts do not block, resize, or alter any live trade.",
        f"- Comparable historical baseline: {payload.get('historical_comparable_trades', 0)} trades; "
        f"fresh sample: {payload.get('fresh_comparable_trades', 0)}.",
        "",
    ]
    if payload.get("conclusions_withheld"):
        lines.extend([
            "**Conclusions withheld because canonical broker reconciliation is incomplete.**",
            "",
        ])

    lines.extend([
        "### Today's Recorded Metrics",
        "",
        "| Order | Direction | Phase | Score | CQ | MAS | ABS | CONF | Shadow Cohort | P&L |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ])
    today_rows = payload.get("today_trades") or []
    if today_rows:
        for trade in today_rows:
            cohorts = []
            if (
                trade.get("phase") == "EARLY_CONTINUATION"
                and float(trade.get("conf") or 0) >= 4.0
            ):
                cohorts.append("EC + CONF≥4 candidate")
            else:
                cohorts.append("primary comparator")
            if trade.get("phase") == "ESTABLISHED":
                cohorts.append(f"Established {trade.get('direction')} shadow reject")
            lines.append(
                f"| {trade.get('broker_entry_order_id')} | {trade.get('direction')} "
                f"| {trade.get('phase')} | {float(trade.get('checklist_score') or 0):.0f} "
                f"| {float(trade.get('cq') or 0):.2f} "
                f"| {float(trade.get('mas') or 0):.2f} | {float(trade.get('abs') or 0):.2f} "
                f"| {float(trade.get('conf') or 0):.2f} | {', '.join(cohorts)} "
                f"| ${float(trade.get('pnl_dollars') or 0):.2f} |"
            )
    else:
        lines.append("| — | — | No comparable trades | — | — | — | — | — | — | $0.00 |")
    lines.append("")

    labels = {
        "early_continuation_conf_4_candidate": "Early Continuation + CONF ≥4",
        "all_other_complete_comparator": "All other complete trades",
        "established_call_shadow_reject": "Established CALL shadow reject",
        "non_established_call_comparator": "Non-Established CALL comparator",
        "established_put_shadow_reject": "Established PUT shadow reject",
        "non_established_put_comparator": "Non-Established PUT comparator",
    }
    for title, key in (
        ("Historical Context", "historical_cohorts"),
        ("Fresh Forward Sample", "fresh_cohorts"),
    ):
        lines.extend([
            f"### {title}",
            "",
            "| Cohort | Trades | W-L | Win Rate | P&L | Average | CALL/PUT |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for name, stats in (payload.get(key) or {}).items():
            win_rate = stats.get("win_rate")
            rate_text = f"{win_rate:.1%}" if win_rate is not None else "N/A"
            average = stats.get("average_pnl_dollars")
            average_text = f"${average:.2f}" if average is not None else "N/A"
            directions = stats.get("directions") or {}
            lines.append(
                f"| {labels.get(name, name)} | {stats.get('trades', 0)} "
                f"| {stats.get('wins', 0)}-{stats.get('losses', 0)} | {rate_text} "
                f"| ${float(stats.get('pnl_dollars') or 0):.2f} | {average_text} "
                f"| {directions.get('CALL', 0)}/{directions.get('PUT', 0)} |"
            )
        lines.append("")

    score_study = payload.get("checklist_score_study") or {}
    lines.extend([
        "### Weighted Checklist Score Study",
        "",
        f"- {score_study.get('score_semantics', '')}",
        "- Results are separated by direction and lifecycle phase; a higher point total is not assumed to be better.",
        "",
    ])
    for title, key in (
        ("Historical Context", "historical"),
        ("Fresh Forward Sample", "fresh"),
    ):
        tables = score_study.get(key) or {}
        lines.extend([
            f"#### {title}",
            "",
            "| Direction | Score | Trades | W-L | Win Rate | P&L | Average |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        direction_tables = tables.get("by_direction_and_phase") or {}
        for direction in ("CALL", "PUT"):
            overall = (direction_tables.get(direction) or {}).get("all_phases") or {}
            for score in CHECKLIST_SCORES:
                stats = overall.get(str(score)) or {}
                rate = stats.get("win_rate")
                rate_text = f"{rate:.1%}" if rate is not None else "N/A"
                average = stats.get("average_pnl_dollars")
                average_text = f"${average:.2f}" if average is not None else "N/A"
                lines.append(
                    f"| {direction} | {score} | {stats.get('trades', 0)} "
                    f"| {stats.get('wins', 0)}-{stats.get('losses', 0)} "
                    f"| {rate_text} | ${float(stats.get('pnl_dollars') or 0):.2f} "
                    f"| {average_text} |"
                )
        lines.append("")

    lines.extend([
        "### Indicator Weight Shadow Comparisons",
        "",
        "- Each indicator is compared with trades of the same direction where that indicator was absent.",
        "- The gate requires at least 20 fresh present and 20 fresh absent trades across at least two lifecycle phases.",
        "",
        "| Hypothesis | Sample | Present W-L | Present P&L | Absent W-L | Absent P&L | Decision |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ])
    for name, hypothesis in (
        (score_study and payload.get("indicator_weight_study") or {}).get("hypotheses", {})
    ).items():
        historical = hypothesis.get("historical") or {}
        present = historical.get("present") or {}
        absent = historical.get("absent_same_direction") or {}
        lines.append(
            f"| {name} | Historical | {present.get('wins', 0)}-{present.get('losses', 0)} "
            f"| ${float(present.get('pnl_dollars') or 0):.2f} "
            f"| {absent.get('wins', 0)}-{absent.get('losses', 0)} "
            f"| ${float(absent.get('pnl_dollars') or 0):.2f} "
            f"| {hypothesis.get('decision')} |"
        )
        fresh_hypothesis = hypothesis.get("fresh") or {}
        present = fresh_hypothesis.get("present") or {}
        absent = fresh_hypothesis.get("absent_same_direction") or {}
        lines.append(
            f"| {name} | Fresh | {present.get('wins', 0)}-{present.get('losses', 0)} "
            f"| ${float(present.get('pnl_dollars') or 0):.2f} "
            f"| {absent.get('wins', 0)}-{absent.get('losses', 0)} "
            f"| ${float(absent.get('pnl_dollars') or 0):.2f} "
            f"| {hypothesis.get('decision')} |"
        )
    lines.extend(["", "### Locked Evidence Gates", ""])
    for name, hypothesis in (payload.get("hypotheses") or {}).items():
        lines.append(f"- **{name}: {hypothesis.get('decision')}**")
        for check, passed in (hypothesis.get("checks") or {}).items():
            lines.append(f"  - {'PASS' if passed else 'WAIT'} — {check}")
    lines.extend([
        "",
        "- A passing gate permits discussion and human review only. It cannot change live admission logic automatically.",
        "",
    ])
    return "\n".join(lines)


def write_entry_quality_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path, Path]:
    trades, coverage = load_study_trades(root=root)
    reconciliation = _load_json(
        root / "reports" / "daily_loss_attribution"
        / f"daily_loss_attribution_{trading_date}.json"
    ).get("reconciliation") or {}
    payload = evaluate_entry_quality_shadow(
        trades,
        trading_date=trading_date,
        reconciliation=reconciliation,
    )
    payload["generated_at"] = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")
    payload["coverage"] = coverage

    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"entry_quality_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_entry_quality_shadow_markdown(payload) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "broker_entry_order_id", "trade_date", "direction", "phase",
            "checklist_score", "indicator_labels", "cq", "mas", "abs", "conf",
            "pnl_dollars", "fresh",
            "early_continuation_conf_4_candidate", "established_shadow_reject",
            "call_breaks_previous_high", "call_macd_improving",
            "put_bearish_volume_confirming",
        ])
        for trade in trades:
            indicators = trade.get("indicator_labels") or []
            writer.writerow([
                trade.get("broker_entry_order_id"), trade.get("trade_date"),
                trade.get("direction"), trade.get("phase"),
                trade.get("checklist_score"), "|".join(indicators), trade.get("cq"),
                trade.get("mas"), trade.get("abs"), trade.get("conf"),
                trade.get("pnl_dollars"),
                int(str(trade.get("trade_date") or "") >= FRESH_START_DATE),
                int(
                    trade.get("phase") == "EARLY_CONTINUATION"
                    and float(trade.get("conf") or 0) >= 4.0
                ),
                int(trade.get("phase") == "ESTABLISHED"),
                int(
                    trade.get("direction") == "CALL"
                    and "breaks_prev_high" in indicators
                ),
                int(
                    trade.get("direction") == "CALL"
                    and "macd_improving" in indicators
                ),
                int(
                    trade.get("direction") == "PUT"
                    and "volume_confirming_bearish_move" in indicators
                ),
            ])
    return payload, json_path, csv_path, md_path
