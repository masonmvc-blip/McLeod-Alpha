from __future__ import annotations

from dataclasses import dataclass, field

from .thesis_graph import ThesisDefinition


SUPPORTED_LABELS = {"supports thesis", "weakens thesis", "neutral", "unknown"}


@dataclass(frozen=True)
class ThesisEvidence:
    evidence_id: str
    fact: str
    source: str
    observed_date: str
    confidence: float
    materiality: float
    recency: float


@dataclass(frozen=True)
class ClassifiedEvidence:
    evidence_id: str
    fact: str
    source: str
    observed_date: str
    confidence: float
    materiality: float
    recency: float
    classification: str
    rationale: str
    weighted_impact: float
    contradiction_score: float


@dataclass(frozen=True)
class EvidenceSummary:
    supporting: tuple[ClassifiedEvidence, ...] = field(default_factory=tuple)
    contradictory: tuple[ClassifiedEvidence, ...] = field(default_factory=tuple)
    neutral: tuple[ClassifiedEvidence, ...] = field(default_factory=tuple)
    unknown: tuple[ClassifiedEvidence, ...] = field(default_factory=tuple)


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _weighted_impact(*, confidence: float, materiality: float, recency: float) -> float:
    return round((_clamp(confidence) * 0.45) + (_clamp(materiality) * 0.35) + (_clamp(recency) * 0.20), 6)


def _tokenize(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in _normalize(text))
    tokens = {token for token in normalized.split() if token}
    return tokens


def _lexicon(thesis: ThesisDefinition) -> tuple[set[str], set[str]]:
    support_terms: set[str] = set()
    contradiction_terms: set[str] = set()

    positive_sections = (
        thesis.core_assumptions,
        thesis.competitive_advantages,
        thesis.growth_drivers,
        thesis.valuation_assumptions,
        thesis.capital_allocation_assumptions,
        thesis.key_metrics,
        thesis.expected_catalysts,
    )
    negative_sections = (
        thesis.risks,
        thesis.disconfirming_evidence,
        thesis.invalidation_criteria,
    )

    for section in positive_sections:
        for text in section:
            support_terms.update(_tokenize(text))
    for section in negative_sections:
        for text in section:
            contradiction_terms.update(_tokenize(text))

    support_terms -= contradiction_terms
    contradiction_terms -= support_terms
    return support_terms, contradiction_terms


def classify_evidence(evidence: ThesisEvidence, thesis: ThesisDefinition) -> ClassifiedEvidence:
    fact = _normalize(evidence.fact)
    lowered_fact = fact.lower()
    tokens = _tokenize(fact)
    support_terms, contradiction_terms = _lexicon(thesis)

    support_hits = len(tokens & support_terms)
    contradiction_hits = len(tokens & contradiction_terms)

    impact = _weighted_impact(
        confidence=evidence.confidence,
        materiality=evidence.materiality,
        recency=evidence.recency,
    )

    has_negation = any(term in lowered_fact for term in (" no ", "not ", "without ", "lack ", "missing ", "absent ")) or lowered_fact.startswith("no ")

    if has_negation and support_hits > 0 and contradiction_hits == 0:
        label = "neutral"
        rationale = "Supportive terms appeared in a negated context."
        contradiction_score = 0.0
    elif support_hits > contradiction_hits and support_hits > 0:
        label = "supports thesis"
        rationale = f"Matched {support_hits} supportive thesis terms."
        contradiction_score = 0.0
    elif contradiction_hits > support_hits and contradiction_hits > 0:
        label = "weakens thesis"
        rationale = f"Matched {contradiction_hits} contradictory thesis terms."
        contradiction_score = round(impact, 6)
    elif support_hits == contradiction_hits and support_hits > 0:
        label = "neutral"
        rationale = "Balanced supportive and contradictory thesis term matches."
        contradiction_score = round(impact * 0.5, 6)
    elif any(term in lowered_fact for term in ("guidance", "beat", "expansion", "share gain", "acceleration")):
        label = "supports thesis"
        rationale = "Matched supportive catalyst heuristic."
        contradiction_score = 0.0
    elif any(term in lowered_fact for term in ("miss", "slowdown", "impairment", "compression", "churn", "downgrade")):
        label = "weakens thesis"
        rationale = "Matched contradictory risk heuristic."
        contradiction_score = round(impact, 6)
    elif tokens:
        label = "neutral"
        rationale = "Fact has content but no thesis-specific directional match."
        contradiction_score = 0.0
    else:
        label = "unknown"
        rationale = "Fact is empty after normalization."
        contradiction_score = 0.0

    if label not in SUPPORTED_LABELS:
        label = "unknown"

    return ClassifiedEvidence(
        evidence_id=_normalize(evidence.evidence_id),
        fact=fact,
        source=_normalize(evidence.source),
        observed_date=_normalize(evidence.observed_date),
        confidence=round(_clamp(evidence.confidence), 6),
        materiality=round(_clamp(evidence.materiality), 6),
        recency=round(_clamp(evidence.recency), 6),
        classification=label,
        rationale=rationale,
        weighted_impact=impact,
        contradiction_score=contradiction_score,
    )


def summarize_classifications(items: tuple[ClassifiedEvidence, ...]) -> EvidenceSummary:
    supporting: list[ClassifiedEvidence] = []
    contradictory: list[ClassifiedEvidence] = []
    neutral: list[ClassifiedEvidence] = []
    unknown: list[ClassifiedEvidence] = []

    for item in items:
        if item.classification == "supports thesis":
            supporting.append(item)
        elif item.classification == "weakens thesis":
            contradictory.append(item)
        elif item.classification == "neutral":
            neutral.append(item)
        else:
            unknown.append(item)

    ordered = lambda seq: tuple(sorted(seq, key=lambda item: (item.observed_date, item.evidence_id, item.fact)))
    return EvidenceSummary(
        supporting=ordered(supporting),
        contradictory=ordered(contradictory),
        neutral=ordered(neutral),
        unknown=ordered(unknown),
    )
