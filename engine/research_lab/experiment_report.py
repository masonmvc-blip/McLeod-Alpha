from __future__ import annotations

from typing import Any


def summary_markdown(experiment: dict[str, Any], metrics: dict[str, float], statistics: dict[str, Any]) -> str:
    lines = [f"# Experiment {experiment['experiment_id']}", "", f"Status: **{experiment['status']}**", "", "## Metrics", ""]
    lines.extend(f"- {key}: {value:.8f}" for key, value in sorted(metrics.items()))
    lines.extend(("", "## Statistics", ""))
    lines.extend(f"- {key}: {value}" for key, value in sorted(statistics.items()))
    return "\n".join(lines) + "\n"