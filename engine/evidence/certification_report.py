from __future__ import annotations

from .certification_schema import Certification


def decision_markdown(certification: Certification) -> bytes:
    lines = [f"# Evidence Certification: {certification.decision}", "", f"Experiment: {certification.experiment_id}", f"Policy: {certification.policy_id} v{certification.policy_version}", "", "## Rationale"]
    lines.extend(f"- {reason}" for reason in certification.rationale)
    return ("\n".join(lines) + "\n").encode("utf-8")