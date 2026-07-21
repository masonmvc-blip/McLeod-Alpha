import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from engine.memory import get_memory


EASTERN_TZ = ZoneInfo("America/New_York")
OPPORTUNITY_LOG_DIR = Path("data/reports/opportunity_logs")
SPY_HISTORY_PATH = Path("data/spy_1min_history.csv")
REPORTS_DIR = Path("reports")

ESTIMATED_OPTION_MOVE_MULTIPLIER = 5.0
TOP_MISSED_OPPORTUNITIES_LIMIT = 10
RESEARCH_CANDIDATE_MINIMUM_SAMPLE_SIZE = 10


@dataclass
class ReviewPaths:
    html: Path
    csv: Path
    json: Path


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(EASTERN_TZ)


def _load_events(trade_date: str) -> List[Dict[str, Any]]:
    path = OPPORTUNITY_LOG_DIR / f"opportunity_setups_{trade_date}.jsonl"
    if not path.exists():
        return []

    events: List[Dict[str, Any]] = []
    seen = set()
    for line in get_memory().read_report_text(path, encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        event_id = str(payload.get("event_id") or "").strip()
        if event_id and event_id in seen:
            continue
        if event_id:
            seen.add(event_id)
        events.append(payload)
    return events


def _load_spy_candles(trade_date: str) -> List[Dict[str, Any]]:
    if not SPY_HISTORY_PATH.exists():
        return []

    out: List[Dict[str, Any]] = []
    reader = csv.DictReader(get_memory().read_report_text(SPY_HISTORY_PATH, encoding="utf-8").splitlines())
    for row in reader:
            dt = _parse_dt(row.get("datetime"))
            if dt is None:
                continue
            if dt.date().isoformat() != trade_date:
                continue
            try:
                out.append(
                    {
                        "datetime": dt,
                        "open": float(row.get("open") or 0.0),
                        "high": float(row.get("high") or 0.0),
                        "low": float(row.get("low") or 0.0),
                        "close": float(row.get("close") or 0.0),
                    }
                )
            except Exception:
                continue

    out.sort(key=lambda x: x["datetime"])
    return out


def _classify_setup_type(event: Dict[str, Any]) -> str:
    regime = str(event.get("market_regime") or "").upper()
    ema10_slope = event.get("ema10_slope_3")
    ema20_slope = event.get("ema20_slope_3")
    macd_slope = event.get("macd_histogram_slope_3")
    high_break = event.get("recent_high_break")
    low_break = event.get("recent_low_break")

    if regime in {"BULL_TREND", "BEAR_TREND"}:
        if (ema10_slope is not None and ema20_slope is not None and ((ema10_slope > 0 > ema20_slope) or (ema10_slope < 0 < ema20_slope))):
            return "Trend Transition"
        if high_break or low_break:
            return "Trend Continuation"
        return "Trend Continuation"

    if macd_slope is not None and abs(float(macd_slope)) > 0.05:
        return "Reversal"

    if str(event.get("candle_overlap_status") or "") == "OVERLAP":
        return "Range/Chop"

    return "Unclassified"


def _estimate_option_returns(direction: str, entry_price: float, price: float) -> float:
    if entry_price <= 0:
        return 0.0
    spy_return_pct = ((price - entry_price) / entry_price) * 100.0
    if direction.upper() == "PUT":
        spy_return_pct = -spy_return_pct
    return spy_return_pct * ESTIMATED_OPTION_MOVE_MULTIPLIER


def _enrich_event_outcomes(event: Dict[str, Any], candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    event_time = _parse_dt(event.get("candle_time_et"))
    if event_time is None:
        event["post_evaluation_tracking"] = None
        event["outcome_classification"] = "scratch/no meaningful move"
        event["estimated_option_outcome"] = {
            "is_estimate": True,
            "label": "estimate_unavailable",
        }
        return event

    entry_price = float(event.get("spy_price") or 0.0)
    direction = str(event.get("direction") or "CALL").upper()
    window_end = event_time + timedelta(minutes=15)

    future = [c for c in candles if c["datetime"] > event_time and c["datetime"] <= window_end]

    if not future or entry_price <= 0:
        event["post_evaluation_tracking"] = {
            "window_minutes": 15,
            "future_candles_used": 0,
            "max_favorable_spy_move": 0.0,
            "max_adverse_spy_move": 0.0,
            "first_threshold_hit": None,
        }
        event["outcome_classification"] = "scratch/no meaningful move"
        event["estimated_option_outcome"] = {
            "is_estimate": True,
            "label": "estimate_unavailable",
            "reliable_option_quotes_available": False,
            "estimated_option_mfe_pct": None,
            "estimated_option_mae_pct": None,
        }
        return event

    favorable_moves: List[float] = []
    adverse_moves: List[float] = []
    threshold_hits: List[tuple[datetime, str]] = []

    for candle in future:
        if direction == "CALL":
            favorable_moves.append(candle["high"] - entry_price)
            adverse_moves.append(candle["low"] - entry_price)
        else:
            favorable_moves.append(entry_price - candle["low"])
            adverse_moves.append(entry_price - candle["high"])

        est_ret = _estimate_option_returns(direction, entry_price, candle["close"])
        if est_ret >= 6:
            threshold_hits.append((candle["datetime"], "+6%"))
        elif est_ret >= 5:
            threshold_hits.append((candle["datetime"], "+5%"))
        elif est_ret >= 4:
            threshold_hits.append((candle["datetime"], "+4%"))
        elif est_ret <= -5:
            threshold_hits.append((candle["datetime"], "-5%"))

    max_favorable = max(favorable_moves) if favorable_moves else 0.0
    max_adverse = min(adverse_moves) if adverse_moves else 0.0

    est_returns = [_estimate_option_returns(direction, entry_price, c["close"]) for c in future]
    estimated_mfe = max(est_returns) if est_returns else None
    estimated_mae = min(est_returns) if est_returns else None

    first_hit = None
    first_hit_time = None
    if threshold_hits:
        threshold_hits.sort(key=lambda x: x[0])
        first_hit_time, first_hit = threshold_hits[0]

    if estimated_mfe is not None and estimated_mfe >= 4:
        outcome = "profitable opportunity missed"
    elif estimated_mae is not None and estimated_mae <= -5:
        outcome = "loss correctly avoided"
    else:
        outcome = "scratch/no meaningful move"

    horizon_outcomes = {}
    for minutes in (1, 3, 5, 10, 15):
        horizon_candles = [c for c in future if c["datetime"] <= event_time + timedelta(minutes=minutes)]
        if not horizon_candles:
            horizon_outcomes[str(minutes)] = None
            continue
        close_return = _estimate_option_returns(direction, entry_price, horizon_candles[-1]["close"])
        high_returns = [
            _estimate_option_returns(direction, entry_price, c["high"] if direction == "CALL" else c["low"])
            for c in horizon_candles
        ]
        low_returns = [
            _estimate_option_returns(direction, entry_price, c["low"] if direction == "CALL" else c["high"])
            for c in horizon_candles
        ]
        horizon_outcomes[str(minutes)] = {
            "estimated_option_return_pct": round(close_return, 4),
            "estimated_option_mfe_pct": round(max(high_returns), 4),
            "estimated_option_mae_pct": round(min(low_returns), 4),
            "future_candles_used": len(horizon_candles),
        }

    event["post_evaluation_tracking"] = {
        "window_minutes": 15,
        "future_candles_used": len(future),
        "max_favorable_spy_move": round(max_favorable, 6),
        "max_adverse_spy_move": round(max_adverse, 6),
        "first_threshold_hit": first_hit,
        "first_threshold_hit_time_et": first_hit_time.isoformat() if first_hit_time else None,
        "fixed_horizon_outcomes": horizon_outcomes,
    }
    if not event.get("entered"):
        event["post_rejection_tracking"] = event["post_evaluation_tracking"]
    event["outcome_classification"] = outcome
    event["estimated_option_outcome"] = {
        "is_estimate": True,
        "label": "estimated_from_spy_proxy",
        "reliable_option_quotes_available": False,
        "estimated_option_mfe_pct": round(estimated_mfe, 4) if estimated_mfe is not None else None,
        "estimated_option_mae_pct": round(estimated_mae, 4) if estimated_mae is not None else None,
    }
    return event


def _bucket(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        v = float(value)
    except Exception:
        return str(value)
    return f"{int(v)}-{int(v) + 1}" if v >= 0 else f"{int(v) - 1}-{int(v)}"


def _win_rate_and_avg_return(events: List[Dict[str, Any]], field_name: str) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[float]] = defaultdict(list)
    for event in events:
        outcome = event.get("estimated_option_outcome") or {}
        ret = outcome.get("estimated_option_mfe_pct")
        if ret is None:
            continue
        grouped[_bucket(event.get(field_name))].append(float(ret))

    rows: List[Dict[str, Any]] = []
    for bucket_name, vals in sorted(grouped.items()):
        wins = sum(1 for v in vals if v >= 4)
        rows.append(
            {
                "bucket": bucket_name,
                "count": len(vals),
                "win_rate_pct": round((wins / len(vals)) * 100.0, 2) if vals else 0.0,
                "avg_estimated_return_pct": round(sum(vals) / len(vals), 4) if vals else 0.0,
            }
        )
    return rows


def _near_miss_reason(reason: str) -> tuple[bool, int]:
    normalized = str(reason or "").strip().lower()
    if "regime mismatch (no_trade)" in normalized:
        return False, 0
    if "score below threshold by 1" in normalized:
        return True, 3
    if "score below threshold by 2" in normalized:
        return True, 2
    if normalized in {"not entered", "entry not entered"}:
        return True, 2
    if any(marker in normalized for marker in ("qualified", "operational", "stale", "rate limit", "pending fill")):
        return True, 1
    return False, 0


def _research_status(observations: int) -> str:
    if observations >= 100:
        return "promotion_review_requires_cross_regime_validation"
    if observations >= 30:
        return "eligible_for_deep_validation"
    if observations >= RESEARCH_CANDIDATE_MINIMUM_SAMPLE_SIZE:
        return "candidate_for_validation"
    return "exploratory_insufficient_sample"


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _near_miss_pattern(event: Dict[str, Any], reason: str) -> str:
    normalized = reason.lower()
    direction = str(event.get("direction") or "UNKNOWN").upper()
    stage = event.get("stage")
    if isinstance(stage, dict):
        stage = stage.get("stage") or stage.get("value") or stage.get("label")
    if "score below threshold by 1" in normalized:
        return f"{direction} missed by 1 point"
    if "score below threshold by 2" in normalized:
        return f"{direction} missed by 2 points"
    if normalized in {"not entered", "entry not entered"}:
        return f"Stage {stage if stage is not None else 'unknown'} Not Entered"
    return f"{direction} {reason}"


def _eligible_near_miss_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    eligible_events: List[Dict[str, Any]] = []
    for event in events:
        if event.get("entered") or str(event.get("market_regime") or "").upper() == "NO_TRADE":
            continue
        eligible, _ = _near_miss_reason(str(event.get("rejection_reason") or "UNKNOWN"))
        if eligible:
            eligible_events.append(event)
    return eligible_events


def _top_missed_opportunities(events: List[Dict[str, Any]], cohort_events: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    rejected = [event for event in events if not event.get("entered")]
    eligible_cohort = _eligible_near_miss_events(cohort_events if cohort_events is not None else events)
    reason_counts = Counter(str(event.get("rejection_reason") or "UNKNOWN") for event in eligible_cohort)
    pattern_counts = Counter(
        _near_miss_pattern(event, str(event.get("rejection_reason") or "UNKNOWN"))
        for event in eligible_cohort
    )
    ranked: List[Dict[str, Any]] = []

    for event in rejected:
        if str(event.get("market_regime") or "").upper() == "NO_TRADE":
            continue
        reason = str(event.get("rejection_reason") or "UNKNOWN")
        eligible, proximity_weight = _near_miss_reason(reason)
        if not eligible:
            continue

        estimated = event.get("estimated_option_outcome") or {}
        tracking = event.get("post_rejection_tracking") or {}
        mfe_value = _number(estimated.get("estimated_option_mfe_pct")) or 0.0
        mae_value = _number(estimated.get("estimated_option_mae_pct")) or 0.0

        cohort_size = int(reason_counts[reason])
        pattern = _near_miss_pattern(event, reason)
        pattern_count = int(pattern_counts[pattern])
        repeatability_component = min(pattern_count / RESEARCH_CANDIDATE_MINIMUM_SAMPLE_SIZE, 1.0) * 40.0
        proximity_component = (proximity_weight / 3.0) * 25.0
        opportunity_component = min(max(mfe_value, 0.0) / 20.0, 1.0) * 20.0
        cohort_component = min(cohort_size / 30.0, 1.0) * 15.0
        learning_score = repeatability_component + proximity_component + opportunity_component + cohort_component
        research_rating = "research_candidate" if mfe_value >= 4.0 else "borderline"

        research = event.get("research") or {}
        shadow_state = event.get("shadow_market_state") or {}
        ranked.append({
            "event_id": event.get("event_id"),
            "time_et": event.get("candle_time_et") or event.get("evaluation_time_et"),
            "direction": event.get("direction"),
            "reason_not_taken": reason,
            "market_state": research.get("trend_state") or shadow_state.get("state") or event.get("market_regime"),
            "market_regime": event.get("market_regime"),
            "trend_stage": event.get("stage"),
            "cq": event.get("cq"),
            "adx_14": event.get("adx_14"),
            "score_distance_to_threshold": event.get("score_distance_to_threshold"),
            "estimated_option_mfe_pct": round(mfe_value, 4),
            "estimated_option_mae_pct": round(mae_value, 4),
            "max_favorable_spy_move": tracking.get("max_favorable_spy_move"),
            "max_adverse_spy_move": tracking.get("max_adverse_spy_move"),
            "first_threshold_hit": tracking.get("first_threshold_hit"),
            "first_threshold_hit_time_et": tracking.get("first_threshold_hit_time_et"),
            "pattern": pattern,
            "pattern_observations": pattern_count,
            "rejection_cohort_observations": cohort_size,
            "learning_value_components": {
                "pattern_repeatability": round(repeatability_component, 4),
                "threshold_proximity": round(proximity_component, 4),
                "subsequent_opportunity": round(opportunity_component, 4),
                "cohort_size": round(cohort_component, 4),
            },
            "research_rating": research_rating,
            "manual_review_label": "unreviewed",
            "research_status": _research_status(cohort_size),
            "promotion_eligible": False,
            "learning_score": round(learning_score, 4),
            "outcome_note": "Estimated from the underlying SPY path; no historical option quotes are reconstructed.",
        })

    return sorted(
        ranked,
        key=lambda row: (row["learning_score"], row["estimated_option_mfe_pct"]),
        reverse=True,
    )[:TOP_MISSED_OPPORTUNITIES_LIMIT]


def _recurring_near_misses(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in _eligible_near_miss_events(events):
        reason = str(event.get("rejection_reason") or "UNKNOWN")
        groups[_near_miss_pattern(event, reason)].append(event)

    rows: List[Dict[str, Any]] = []
    for pattern, members in groups.items():
        mfes = [_number((event.get("estimated_option_outcome") or {}).get("estimated_option_mfe_pct")) for event in members]
        maes = [_number((event.get("estimated_option_outcome") or {}).get("estimated_option_mae_pct")) for event in members]
        valid_mfes = [value for value in mfes if value is not None]
        valid_maes = [value for value in maes if value is not None]
        if not valid_mfes:
            continue
        observations = len(members)
        average_mfe = sum(valid_mfes) / len(valid_mfes)
        average_mae = sum(valid_maes) / len(valid_maes) if valid_maes else None
        rows.append({
            "pattern": pattern,
            "count": observations,
            "avg_estimated_option_mfe_pct": round(average_mfe, 4),
            "avg_estimated_option_mae_pct": round(average_mae, 4) if average_mae is not None else None,
            "research_regret_pct": round(average_mfe, 4),
            "rejected_realized_value_pct": 0.0,
            "research_status": _research_status(observations),
            "recommendation": "formal validation candidate" if observations >= 30 else "continue observation",
            "promotion_eligible": False,
            "outcome_note": "Expected value and research regret use estimated SPY-proxy option MFE, not executable option P&L.",
        })
    return sorted(rows, key=lambda row: (row["count"], row["avg_estimated_option_mfe_pct"]), reverse=True)


def _load_prior_review_events(trade_date: str) -> List[Dict[str, Any]]:
    prior_events: List[Dict[str, Any]] = []
    current_name = f"daily_opportunity_review_{trade_date}.json"
    for path in REPORTS_DIR.glob("daily_opportunity_review_*.json"):
        if path.name == current_name:
            continue
        try:
            payload = json.loads(get_memory().read_report_text(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        prior_events.extend(payload.get("evaluated_setups") or [])
    return prior_events


def _build_summary(events: List[Dict[str, Any]], historical_events: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    entered = [e for e in events if e.get("entered")]
    rejected = [e for e in events if not e.get("entered")]

    profitable_missed = [e for e in rejected if e.get("outcome_classification") == "profitable opportunity missed"]
    losses_avoided = [e for e in rejected if e.get("outcome_classification") == "loss correctly avoided"]

    by_reason = Counter(str(e.get("rejection_reason") or "UNKNOWN") for e in rejected)
    by_setup_type = Counter(str(e.get("setup_type") or "Unclassified") for e in events)

    top_rules = Counter()
    for e in profitable_missed:
        for p in (e.get("positive_signals") or []):
            top_rules[str(p)] += 1

    costly_rejections = by_reason.most_common(3)

    largest_missed = sorted(
        profitable_missed,
        key=lambda x: float(((x.get("estimated_option_outcome") or {}).get("estimated_option_mfe_pct") or 0.0)),
        reverse=True,
    )[:3]

    metric_fields = [
        "stage",
        "cq",
        "mas",
        "tes",
        "mes",
        "confidence",
        "absorption_score",
    ]

    buckets = {name: _win_rate_and_avg_return(events, name) for name in metric_fields}
    cohort_events = (historical_events or []) + events
    top_missed_opportunities = _top_missed_opportunities(events, cohort_events)
    recurring_near_misses = _recurring_near_misses(cohort_events)

    return {
        "total_evaluations": len(events),
        "trades_taken": len(entered),
        "trades_rejected": len(rejected),
        "profitable_opportunities_missed": len(profitable_missed),
        "losses_correctly_avoided": len(losses_avoided),
        "results_by_rejection_reason": dict(by_reason),
        "results_by_setup_type": dict(by_setup_type),
        "three_most_valuable_rules": [k for k, _ in top_rules.most_common(3)],
        "three_most_costly_rejection_reasons": [k for k, _ in costly_rejections],
        "largest_missed_moves": [
            {
                "timestamp_et": e.get("candle_time_et"),
                "direction": e.get("direction"),
                "estimated_option_mfe_pct": (e.get("estimated_option_outcome") or {}).get("estimated_option_mfe_pct"),
            }
            for e in largest_missed
        ],
        "top_missed_opportunities": top_missed_opportunities,
        "recurring_near_misses": recurring_near_misses,
        "decision_regret_rate": {
            "definition": "Average estimated post-rejection option MFE for each rejected pattern; rejected realized value is recorded as zero.",
            "outcome_note": "Research-only SPY-proxy estimate. It is not actual executable option P&L or an instruction to change live rules.",
            "cohorts": recurring_near_misses,
        },
        "buckets": buckets,
    }


def _to_csv_rows(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for event in events:
        tracking = event.get("post_rejection_tracking") or {}
        estimated = event.get("estimated_option_outcome") or {}
        rows.append(
            {
                "event_id": event.get("event_id"),
                "evaluation_time_et": event.get("evaluation_time_et"),
                "candle_time_et": event.get("candle_time_et"),
                "direction": event.get("direction"),
                "spy_price": event.get("spy_price"),
                "option_selected": event.get("option_selected"),
                "stage": event.get("stage"),
                "cq": event.get("cq"),
                "mas": event.get("mas"),
                "tes": event.get("tes"),
                "mes": event.get("mes"),
                "confidence": event.get("confidence"),
                "absorption_score": event.get("absorption_score"),
                "positive_signals": " | ".join(event.get("positive_signals") or []),
                "penalties": " | ".join(event.get("penalties") or []),
                "entered": event.get("entered"),
                "rejection_reason": event.get("rejection_reason"),
                "score_distance_to_threshold": event.get("score_distance_to_threshold"),
                "market_regime": event.get("market_regime"),
                "setup_type": event.get("setup_type"),
                "ema10_slope_3": event.get("ema10_slope_3"),
                "ema20_slope_3": event.get("ema20_slope_3"),
                "ema10_ema20_separation": event.get("ema10_ema20_separation"),
                "macd_histogram_value": event.get("macd_histogram_value"),
                "macd_histogram_slope_3": event.get("macd_histogram_slope_3"),
                "candle_compression_status": event.get("candle_compression_status"),
                "candle_overlap_status": event.get("candle_overlap_status"),
                "recent_high_break": event.get("recent_high_break"),
                "recent_low_break": event.get("recent_low_break"),
                "max_favorable_spy_move": tracking.get("max_favorable_spy_move"),
                "max_adverse_spy_move": tracking.get("max_adverse_spy_move"),
                "first_threshold_hit": tracking.get("first_threshold_hit"),
                "first_threshold_hit_time_et": tracking.get("first_threshold_hit_time_et"),
                "outcome_classification": event.get("outcome_classification"),
                "estimated_option_mfe_pct": estimated.get("estimated_option_mfe_pct"),
                "estimated_option_mae_pct": estimated.get("estimated_option_mae_pct"),
                "estimate_label": estimated.get("label"),
                "is_estimate": estimated.get("is_estimate"),
                "reliable_option_quotes_available": estimated.get("reliable_option_quotes_available"),
            }
        )
    return rows


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["event_id"]
    get_memory().write_report_csv(path, fieldnames, rows, "daily_opportunity_review", source="daily_opportunity_review")


def _render_html(trade_date: str, summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    def table_from_dict(title: str, data: Dict[str, Any]) -> str:
        body = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in data.items())
        return f"<h3>{title}</h3><table border='1' cellpadding='4' cellspacing='0'><tr><th>Key</th><th>Value</th></tr>{body}</table>"

    def table_from_rows(title: str, rows_in: List[Dict[str, Any]]) -> str:
        if not rows_in:
            return f"<h3>{title}</h3><p>No rows</p>"
        headers = list(rows_in[0].keys())
        th = "".join(f"<th>{h}</th>" for h in headers)
        tr = ""
        for row in rows_in:
            tr += "<tr>" + "".join(f"<td>{row.get(h)}</td>" for h in headers) + "</tr>"
        return f"<h3>{title}</h3><table border='1' cellpadding='4' cellspacing='0'><tr>{th}</tr>{tr}</table>"

    bucket_sections = ""
    for metric_name, bucket_rows in (summary.get("buckets") or {}).items():
        bucket_sections += table_from_rows(f"Win rate and avg return by {metric_name}", bucket_rows)

    largest_missed = table_from_rows("Largest missed moves (ET)", summary.get("largest_missed_moves") or [])
    top_missed = table_from_rows("Top 10 Missed Opportunities (research-only)", summary.get("top_missed_opportunities") or [])
    recurring = table_from_rows("Recurring Near Misses (research-only)", summary.get("recurring_near_misses") or [])

    all_rows_preview = table_from_rows("Evaluated setups (sample)", rows[:50])

    return (
        "<html><head><meta charset='utf-8'><title>Daily Opportunity Review</title></head><body>"
        f"<h1>Daily Opportunity Review - {trade_date}</h1>"
        f"<p>Generated at: {datetime.now(EASTERN_TZ).isoformat()}</p>"
        f"<h2>1. Trades taken</h2><p>{summary.get('trades_taken')}</p>"
        f"<h2>2. Trades rejected</h2><p>{summary.get('trades_rejected')}</p>"
        f"<h2>3. Profitable opportunities missed</h2><p>{summary.get('profitable_opportunities_missed')}</p>"
        f"<h2>4. Losses correctly avoided</h2><p>{summary.get('losses_correctly_avoided')}</p>"
        f"<h2>5. Results by rejection reason</h2>{table_from_dict('Rejection reasons', summary.get('results_by_rejection_reason') or {})}"
        f"<h2>6. Results by setup type</h2>{table_from_dict('Setup type', summary.get('results_by_setup_type') or {})}"
        f"<h2>7. Win rate and average return by Stage, CQ, MAS, TES, MES, Confidence, Absorption bucket</h2>{bucket_sections}"
        f"<h2>8. Three most valuable rules today</h2><p>{', '.join(summary.get('three_most_valuable_rules') or [])}</p>"
        f"<h2>9. Three most costly rejection reasons today</h2><p>{', '.join(summary.get('three_most_costly_rejection_reasons') or [])}</p>"
        f"<h2>10. Exact timestamps of the largest missed moves in Eastern Time</h2>{largest_missed}"
        f"<h2>11. Top 10 Missed Opportunities</h2><p>Ranked by expected learning value, not raw profit. NO_TRADE regime rejections are excluded. Ratings are observational and never change live entry policy.</p>{top_missed}"
        f"<h2>12. Recurring Near Misses</h2><p>Patterns accumulate across prior daily reviews and use the 10, 30, and 100 observation governance thresholds. Decision regret is an estimated research measure, not realized trade P&amp;L.</p>{recurring}"
        f"{all_rows_preview}"
        "</body></html>"
    )


def build_daily_opportunity_review(trade_date: str) -> ReviewPaths:
    out_csv = REPORTS_DIR / f"daily_opportunity_review_{trade_date}.csv"
    out_json = REPORTS_DIR / f"daily_opportunity_review_{trade_date}.json"
    out_html = REPORTS_DIR / f"daily_opportunity_review_{trade_date}.html"

    events = _load_events(trade_date)
    candles = _load_spy_candles(trade_date)
    historical_events = _load_prior_review_events(trade_date)

    enriched: List[Dict[str, Any]] = []
    for event in events:
        event["setup_type"] = _classify_setup_type(event)
        enriched.append(_enrich_event_outcomes(event, candles))

    summary = _build_summary(enriched, historical_events)
    csv_rows = _to_csv_rows(enriched)

    _write_csv(out_csv, csv_rows)
    get_memory().write_report_json(out_json, {"trade_date": trade_date, "generated_at": datetime.now(EASTERN_TZ).isoformat(), "summary": summary, "evaluated_setups": enriched}, "daily_opportunity_review", source="daily_opportunity_review", correlation_id=f"daily-opportunity-review:{trade_date}")
    get_memory().write_report_text(out_html, _render_html(trade_date, summary, csv_rows), "daily_opportunity_review", source="daily_opportunity_review", correlation_id=f"daily-opportunity-review:{trade_date}")
    from reports.trend_quality_report import build_trend_quality_report
    from reports.research_validation import build_research_validation_reports
    from reports.daily_research_advisory import build_daily_research_advisory

    build_trend_quality_report(REPORTS_DIR)
    build_research_validation_reports(REPORTS_DIR)
    build_daily_research_advisory(trade_date, REPORTS_DIR)

    return ReviewPaths(html=out_html, csv=out_csv, json=out_json)
