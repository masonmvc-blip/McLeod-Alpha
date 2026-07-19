from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ThesisDefinition:
    thesis_id: str
    symbol: str
    as_of_date: str
    current_thesis: str
    core_assumptions: tuple[str, ...] = field(default_factory=tuple)
    competitive_advantages: tuple[str, ...] = field(default_factory=tuple)
    growth_drivers: tuple[str, ...] = field(default_factory=tuple)
    valuation_assumptions: tuple[str, ...] = field(default_factory=tuple)
    capital_allocation_assumptions: tuple[str, ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    disconfirming_evidence: tuple[str, ...] = field(default_factory=tuple)
    key_metrics: tuple[str, ...] = field(default_factory=tuple)
    expected_catalysts: tuple[str, ...] = field(default_factory=tuple)
    invalidation_criteria: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, tuple):
                payload[key] = list(value)
        return payload


@dataclass(frozen=True)
class ThesisNode:
    node_type: str
    text: str


@dataclass(frozen=True)
class ThesisEdge:
    source_type: str
    target_type: str
    relation: str


@dataclass(frozen=True)
class ThesisGraph:
    thesis_id: str
    symbol: str
    nodes: tuple[ThesisNode, ...]
    edges: tuple[ThesisEdge, ...]
    unanswered_questions: tuple[str, ...]


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _iter_sections(thesis: ThesisDefinition) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        ("core_assumption", thesis.core_assumptions),
        ("competitive_advantage", thesis.competitive_advantages),
        ("growth_driver", thesis.growth_drivers),
        ("valuation_assumption", thesis.valuation_assumptions),
        ("capital_allocation_assumption", thesis.capital_allocation_assumptions),
        ("risk", thesis.risks),
        ("disconfirming_evidence", thesis.disconfirming_evidence),
        ("key_metric", thesis.key_metrics),
        ("expected_catalyst", thesis.expected_catalysts),
        ("invalidation_criterion", thesis.invalidation_criteria),
    )


def build_thesis_graph(thesis: ThesisDefinition) -> ThesisGraph:
    nodes: list[ThesisNode] = [ThesisNode(node_type="thesis", text=_normalize(thesis.current_thesis))]
    edges: list[ThesisEdge] = []

    for section_type, section_items in _iter_sections(thesis):
        for item in section_items:
            text = _normalize(item)
            if not text:
                continue
            nodes.append(ThesisNode(node_type=section_type, text=text))
            relation = "qualifies" if section_type in {"risk", "disconfirming_evidence", "invalidation_criterion"} else "supports"
            edges.append(ThesisEdge(source_type=section_type, target_type="thesis", relation=relation))

    unanswered_questions = tuple(
        sorted(
            {
                node.text
                for node in nodes
                if "?" in node.text or "TBD" in node.text.upper() or "UNKNOWN" in node.text.upper()
            }
        )
    )

    sorted_nodes = tuple(sorted(nodes, key=lambda item: (item.node_type, item.text)))
    sorted_edges = tuple(sorted(edges, key=lambda item: (item.source_type, item.target_type, item.relation)))

    return ThesisGraph(
        thesis_id=thesis.thesis_id,
        symbol=thesis.symbol,
        nodes=sorted_nodes,
        edges=sorted_edges,
        unanswered_questions=unanswered_questions,
    )
