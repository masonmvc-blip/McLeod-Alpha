from engine.brain.candidate_controls import CandidateControls, candidate_entry_block_reason, candidate_quantity


def _features(**overrides):
    features = {
        "direction": "CALL",
        "momentum_phase": "EARLY_CONTINUATION",
        "confidence_score": 4.0,
        "continuation_quality": {"components": {"distance_from_ema10": {"distance_pct": 0.05}, "pullback_depth": {"depth_candles": 1}}},
        "support_resistance": {"distance_to_resistance_pct": 0.05, "distance_to_support_pct": 0.05},
    }
    features.update(overrides)
    return features


def test_disabled_controls_preserve_entry_and_quantity_baseline():
    controls = CandidateControls()
    assert candidate_entry_block_reason(_features(momentum_phase="ESTABLISHED", confidence_score=0.0), None, controls) is None
    assert candidate_quantity(entry_price=6.0, stop_price=5.0, baseline_quantity=6, controls=controls) == 6


def test_enabled_controls_reject_the_intended_research_conditions():
    controls = CandidateControls(enabled=True, block_low_confidence_established=True, require_structural_room=True)
    assert candidate_entry_block_reason(_features(momentum_phase="ESTABLISHED", confidence_score=3.0), None, controls) == "candidate_low_confidence_established"
    assert candidate_entry_block_reason(_features(support_resistance={"distance_to_resistance_pct": 0.0}), None, CandidateControls(enabled=True, require_structural_room=True)) == "candidate_insufficient_structural_room"


def test_dollar_risk_candidate_caps_quantity_without_exceeding_baseline():
    controls = CandidateControls(enabled=True, use_dollar_risk_sizing=True, max_risk_dollars=100.0)
    assert candidate_quantity(entry_price=6.0, stop_price=5.0, baseline_quantity=6, controls=controls) == 1
    assert candidate_quantity(entry_price=6.0, stop_price=5.75, baseline_quantity=6, controls=controls) == 4