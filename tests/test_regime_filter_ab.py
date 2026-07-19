from pathlib import Path

import pandas as pd

from backtesting.regime_filter_ab import ExperimentConfig, run_regime_filter_ab


def _paths():
    root = Path(__file__).resolve().parent.parent
    csv_path = root / "data" / "historical" / "spy_1m.csv"
    output_dir = root / "backtesting" / "output"
    return root, csv_path, output_dir


def test_regime_filter_ab_validation_rules():
    _, csv_path, output_dir = _paths()
    assert csv_path.exists(), "Historical CSV is required for this validation test"

    result = run_regime_filter_ab(
        csv_path=csv_path,
        output_dir=output_dir,
        config=ExperimentConfig(),
    )

    baseline_df = result["baseline_df"]
    skip_df = result["skip_only_df"]
    constant_df = result["constant_df"]
    blocked_df = result["blocked_df"]
    replacements_df = result["replacements_df"]

    # Skip-only must not exceed baseline count.
    assert len(skip_df) <= len(baseline_df)

    # Constant-sample count can be equal only if enough data exists.
    assert len(constant_df) <= len(baseline_df)

    # Blocked trades must not appear in skip-only accepted trades.
    blocked_keys = set(zip(blocked_df["timestamp"], blocked_df["direction"])) if not blocked_df.empty else set()
    skip_keys = set(
        zip(
            pd.to_datetime(skip_df.get("entry_time", pd.Series(dtype=str)), utc=True).astype(str),
            skip_df.get("direction", pd.Series(dtype=str)).astype(str),
        )
    )
    assert blocked_keys.isdisjoint(skip_keys)

    # Replacement trades must be explicitly identified when count is restored.
    if len(constant_df) == len(baseline_df):
        assert len(replacements_df) == max(0, len(constant_df) - len(skip_df))
        assert "replaced_blocked_sequence" in replacements_df.columns


def test_regime_filter_ab_is_deterministic():
    _, csv_path, output_dir = _paths()

    result_1 = run_regime_filter_ab(
        csv_path=csv_path,
        output_dir=output_dir,
        config=ExperimentConfig(),
    )
    result_2 = run_regime_filter_ab(
        csv_path=csv_path,
        output_dir=output_dir,
        config=ExperimentConfig(),
    )

    assert result_1["baseline_metrics"] == result_2["baseline_metrics"]
    assert result_1["skip_metrics"] == result_2["skip_metrics"]
    assert result_1["constant_metrics"] == result_2["constant_metrics"]

    for key in ["skip", "constant", "blocked", "replacement"]:
        path_1 = result_1["paths"][key]
        path_2 = result_2["paths"][key]
        assert path_1.read_text(encoding="utf-8") == path_2.read_text(encoding="utf-8")
