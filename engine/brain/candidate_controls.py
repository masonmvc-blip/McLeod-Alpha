"""Disabled-by-default research candidates for autonomous entry controls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "autonomous_candidate_controls.json"


@dataclass(frozen=True)
class CandidateControls:
    """Research controls that preserve the current live baseline when disabled."""

    enabled: bool = False
    block_low_confidence_established: bool = False
    block_extended_no_pullback: bool = False
    require_structural_room: bool = False
    require_cost_efficiency: bool = False
    use_dollar_risk_sizing: bool = False
    established_min_confidence: float = 3.5
    max_extension_without_pullback_pct: float = 0.10
    minimum_structural_room_pct: float = 0.02
    max_option_spread_pct: float = 4.0
    max_risk_dollars: float = 100.0


def load_candidate_controls(path: Path | str = DEFAULT_CONFIG_PATH) -> CandidateControls:
    """Load candidate controls, falling back to an inert baseline on bad input."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    values = {name: payload[name] for name in CandidateControls.__dataclass_fields__ if name in payload}
    try:
        return CandidateControls(**values)
    except (TypeError, ValueError):
        return CandidateControls()


def candidate_entry_block_reason(
    features: dict[str, Any], option: dict[str, Any] | None, controls: CandidateControls,
) -> str | None:
    """Return the first enabled rejection, preserving live admission precedence."""
    reasons = candidate_entry_block_reasons(features, option, controls)
    return reasons[0] if reasons else None


def candidate_entry_block_reasons(
    features: dict[str, Any], option: dict[str, Any] | None, controls: CandidateControls,
) -> list[str]:
    """Return every simultaneously failing enabled candidate control."""
    if not controls.enabled:
        return []

    phase = str(features.get("momentum_phase") or "").upper()
    confidence = float(features.get("confidence_score") or 0.0)
    continuation = features.get("continuation_quality") or {}
    components = continuation.get("components") or {}
    extension = abs(float((components.get("distance_from_ema10") or {}).get("distance_pct") or 0.0))
    pullback_candles = int(float((components.get("pullback_depth") or {}).get("depth_candles") or 0))
    structure = features.get("support_resistance") or {}
    if str(features.get("direction") or "").upper() == "CALL":
        room = float(structure.get("distance_to_resistance_pct") or 0.0)
    else:
        room = float(structure.get("distance_to_support_pct") or 0.0)

    reasons: list[str] = []
    if controls.block_low_confidence_established and phase == "ESTABLISHED" and confidence < controls.established_min_confidence:
        reasons.append("candidate_low_confidence_established")
    if controls.block_extended_no_pullback and extension > controls.max_extension_without_pullback_pct and pullback_candles == 0:
        reasons.append("candidate_extended_without_pullback")
    if controls.require_structural_room and room < controls.minimum_structural_room_pct:
        reasons.append("candidate_insufficient_structural_room")
    if controls.require_cost_efficiency and option:
        mark = float(option.get("mark") or 0.0)
        spread = float(option.get("ask") or 0.0) - float(option.get("bid") or 0.0)
        spread_pct = (spread / mark * 100.0) if mark > 0 else float("inf")
        if spread_pct > controls.max_option_spread_pct:
            reasons.append("candidate_transaction_cost")
    return reasons


def candidate_quantity(*, entry_price: float, stop_price: float, baseline_quantity: int, controls: CandidateControls) -> int:
    """Return baseline quantity unless the opt-in dollar-risk candidate is enabled."""
    if not (controls.enabled and controls.use_dollar_risk_sizing):
        return int(baseline_quantity)
    risk_per_contract = abs(float(entry_price) - float(stop_price)) * 100.0
    if risk_per_contract <= 0:
        return 0
    return max(1, min(int(baseline_quantity), int(controls.max_risk_dollars // risk_per_contract)))
