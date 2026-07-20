from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.memory import get_memory

from .evidence_ledger import EvidenceLedger
from .evidence_record import EvidenceLineageRecord, EvidenceRecord


DEFAULT_CHAIN_REPORT_PATH = Path("artifacts") / "cio" / "evidence_ledger" / "evidence_chain_report.md"


@dataclass(frozen=True)
class ReconstructedEvidenceChain:
    target_type: str
    target_id: str
    evidence: tuple[EvidenceRecord, ...]
    lineage: tuple[EvidenceLineageRecord, ...]
    missing_lineage: tuple[str, ...]
    integrity_ok: bool
    report_path: str
    markdown: str


def _parse_date(value: str) -> str:
    return str(value or "").strip()


class EvidenceReplay:
    def __init__(self, ledger: EvidenceLedger) -> None:
        self.ledger = ledger

    def snapshot(self, symbol: str, as_of_date: str) -> tuple[EvidenceRecord, ...]:
        cutoff = _parse_date(as_of_date)
        all_records = [item for item in self.ledger._load_evidence_records() if item.symbol == symbol and item.observed_at <= cutoff]

        superseded_ids: set[str] = set()
        for record in all_records:
            if record.supersedes_evidence_id and record.observed_at <= cutoff:
                superseded_ids.add(record.supersedes_evidence_id)

        live = [item for item in all_records if item.evidence_id not in superseded_ids]
        return tuple(sorted(live, key=lambda item: (item.observed_at, item.evidence_id)))

    def reconstruct_chain(self, target_type: str, target_id: str) -> dict[str, Any]:
        target_type = str(target_type)
        target_id = str(target_id)
        target_links = self.ledger.get_lineage_for_target(target_type, target_id)

        evidence_map = {item.evidence_id: item for item in self.ledger._load_evidence_records()}
        evidence_rows = [evidence_map[item.evidence_id] for item in target_links if item.evidence_id in evidence_map]
        evidence_rows = sorted(evidence_rows, key=lambda item: (item.observed_at, item.evidence_id))

        all_related_links: list[EvidenceLineageRecord] = []
        for evidence in evidence_rows:
            all_related_links.extend(self.ledger.get_lineage_for_evidence(evidence.evidence_id))
        all_related_links = sorted(
            {item.lineage_id: item for item in all_related_links}.values(),
            key=lambda item: (item.created_at, item.target_type, item.target_id, item.lineage_id),
        )

        missing_lineage = tuple(
            sorted(
                evidence.evidence_id
                for evidence in evidence_rows
                if not self.ledger.get_lineage_for_evidence(evidence.evidence_id)
            )
        )

        integrity = self.ledger.verify_integrity()

        chain_payload = {
            "target_type": target_type,
            "target_id": target_id,
            "evidence": [item.to_dict() for item in evidence_rows],
            "lineage": [item.to_dict() for item in all_related_links],
            "missing_lineage": list(missing_lineage),
            "integrity_ok": integrity.ok,
        }
        return chain_payload

    def write_chain_report(self, target_type: str, target_id: str, *, report_path: Path | None = None) -> ReconstructedEvidenceChain:
        chain = self.reconstruct_chain(target_type=target_type, target_id=target_id)
        evidence = tuple(EvidenceRecord.from_dict(item) for item in chain["evidence"])
        lineage = tuple(EvidenceLineageRecord.from_dict(item) for item in chain["lineage"])
        integrity_ok = bool(chain["integrity_ok"])
        missing_lineage = tuple(chain["missing_lineage"])

        markdown = _render_chain_report(
            target_type=target_type,
            target_id=target_id,
            evidence=evidence,
            lineage=lineage,
            missing_lineage=missing_lineage,
            integrity_ok=integrity_ok,
        )

        final_path = Path(report_path or DEFAULT_CHAIN_REPORT_PATH)
        get_memory().write_experiment_text(final_path, markdown, "cio_evidence_chain_report", source="cio_evidence_replay", correlation_id=f"{target_type}:{target_id}")

        return ReconstructedEvidenceChain(
            target_type=target_type,
            target_id=target_id,
            evidence=evidence,
            lineage=lineage,
            missing_lineage=missing_lineage,
            integrity_ok=integrity_ok,
            report_path=str(final_path),
            markdown=markdown,
        )


def _render_chain_report(
    *,
    target_type: str,
    target_id: str,
    evidence: tuple[EvidenceRecord, ...],
    lineage: tuple[EvidenceLineageRecord, ...],
    missing_lineage: tuple[str, ...],
    integrity_ok: bool,
) -> str:
    supporting = [item for item in evidence if item.classification == "supports thesis"]
    contradictory = [item for item in evidence if item.classification == "weakens thesis"]
    superseded = [item for item in evidence if item.supersedes_evidence_id]

    def _lines(items: list[EvidenceRecord]) -> list[str]:
        if not items:
            return ["- None"]
        return [
            f"- [{item.observed_at}] {item.evidence_id} | {item.classification} | {item.related_thesis_component} | {item.headline}"
            for item in sorted(items, key=lambda row: (row.observed_at, row.evidence_id))
        ]

    links_by_type: dict[str, list[EvidenceLineageRecord]] = {
        "ThesisEvaluation": [],
        "DecisionRecord": [],
        "PortfolioPlan": [],
        "RealizedOutcome": [],
    }
    for item in lineage:
        links_by_type.setdefault(item.target_type, []).append(item)

    def _link_lines(target: str) -> list[str]:
        items = sorted(links_by_type.get(target, []), key=lambda row: (row.created_at, row.lineage_id))
        if not items:
            return ["- None"]
        return [
            f"- [{item.created_at}] {item.relationship} | evidence {item.evidence_id} -> {item.target_type}:{item.target_id} | weight {item.influence_weight:.2f} | {item.reason}"
            for item in items
        ]

    timeline = sorted(evidence, key=lambda item: (item.observed_at, item.evidence_id))

    lines: list[str] = [
        "# Evidence Chain Report",
        "",
        "## Audit Target",
        f"- target_type: {target_type}",
        f"- target_id: {target_id}",
        "",
        "## Evidence Timeline",
    ]
    lines.extend(_lines(list(timeline)))

    lines.extend(["", "## Supporting Evidence"])
    lines.extend(_lines(supporting))

    lines.extend(["", "## Contradictory Evidence"])
    lines.extend(_lines(contradictory))

    lines.extend(["", "## Superseded Evidence"])
    lines.extend(_lines(superseded))

    lines.extend(["", "## Thesis Links"])
    lines.extend(_link_lines("ThesisEvaluation"))

    lines.extend(["", "## Decision Links"])
    lines.extend(_link_lines("DecisionRecord"))

    lines.extend(["", "## Portfolio Plan Links"])
    lines.extend(_link_lines("PortfolioPlan"))

    lines.extend(["", "## Outcome Validation"])
    outcome_links = [
        item
        for item in sorted(links_by_type.get("RealizedOutcome", []), key=lambda row: (row.created_at, row.lineage_id))
        if item.relationship in {"validated", "invalidated"}
    ]
    if outcome_links:
        for item in outcome_links:
            lines.append(
                f"- [{item.created_at}] {item.relationship} | evidence {item.evidence_id} -> {item.target_id} | weight {item.influence_weight:.2f}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Missing Lineage"])
    if missing_lineage:
        lines.extend(f"- {item}" for item in missing_lineage)
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Integrity Status",
        f"- ok: {str(integrity_ok).lower()}",
    ])
    return "\n".join(lines) + "\n"
