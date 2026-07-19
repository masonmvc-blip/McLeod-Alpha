from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from typing import Iterable

from .types import (
    EvidenceConclusion,
    EvidenceEngineResult,
    EvidenceSummary,
    NormalizedEvidenceRecord,
    RawEvidenceRecord,
)


class EvidenceValidationError(ValueError):
    pass


class EvidenceEngineModel:
    """Deterministic advisory-only evidence processor.

    The model never calls external systems. It accepts an explicit set of
    public evidence records and produces a deterministic advisory conclusion.
    """

    ALLOWED_POLARITIES = {"support", "oppose", "neutral"}
    ALLOWED_SOURCE_TYPES = {"filing", "transcript", "news", "research", "macro", "industry"}
    REQUIRED_TOPICS = {"valuation", "quality", "growth"}

    def evaluate(
        self,
        *,
        ticker: str,
        as_of: str,
        evidence_records: Iterable[RawEvidenceRecord],
    ) -> EvidenceEngineResult:
        audit_steps: list[str] = []
        records = self._collect(records=evidence_records)
        audit_steps.append("collect")

        normalized = tuple(self._normalize(record=r) for r in records)
        audit_steps.append("normalize")

        validated = tuple(self._validate(as_of=as_of, record=r) for r in normalized)
        audit_steps.append("validate")

        deduped, duplicate_map = self._deduplicate(validated)
        audit_steps.append("deduplicate")

        scores = self._score(as_of=as_of, records=deduped)
        audit_steps.append("score")

        conclusion = self._summarize(ticker=ticker, as_of=as_of, records=deduped, scores=scores)
        audit_steps.append("summarize")

        evidence_by_id = {row.evidence_id: row for row in deduped}
        return EvidenceEngineResult(
            passed=not conclusion.fail_closed,
            collected_count=len(records),
            normalized_count=len(normalized),
            validated_count=len(validated),
            deduplicated_count=len(deduped),
            duplicate_map=duplicate_map,
            evidence_scores=scores,
            evidence_by_id=evidence_by_id,
            conclusion=conclusion,
            audit_steps=tuple(audit_steps),
        )

    def _collect(self, *, records: Iterable[RawEvidenceRecord]) -> tuple[RawEvidenceRecord, ...]:
        collected = tuple(records)
        return tuple(
            sorted(
                collected,
                key=lambda row: (
                    row.ticker.strip().upper(),
                    row.topic.strip().lower(),
                    row.published_at.strip(),
                    row.evidence_id.strip().lower(),
                ),
            )
        )

    def _normalize(self, *, record: RawEvidenceRecord) -> NormalizedEvidenceRecord:
        ticker = record.ticker.strip().upper()
        topic = record.topic.strip().lower()
        title = " ".join(record.title.split())
        publisher = " ".join(record.publisher.split())
        source_url = record.source_url.strip()
        source_type = record.source_type.strip().lower()
        claim = " ".join(record.claim.split())
        polarity = record.polarity.strip().lower()
        evidence_id = record.evidence_id.strip()
        published_at = record.published_at.strip()
        confidence_hint = round(float(record.confidence_hint), 6)
        provenance = dict(sorted((str(k), str(v)) for k, v in record.provenance.items()))
        fingerprint = self._fingerprint(
            ticker=ticker,
            topic=topic,
            title=title,
            publisher=publisher,
            source_url=source_url,
            published_at=published_at,
            claim=claim,
        )
        return NormalizedEvidenceRecord(
            evidence_id=evidence_id,
            ticker=ticker,
            topic=topic,
            title=title,
            publisher=publisher,
            source_url=source_url,
            source_type=source_type,
            published_at=published_at,
            claim=claim,
            polarity=polarity,
            confidence_hint=confidence_hint,
            provenance=provenance,
            fingerprint=fingerprint,
        )

    def _validate(self, *, as_of: str, record: NormalizedEvidenceRecord) -> NormalizedEvidenceRecord:
        required_text_fields = {
            "evidence_id": record.evidence_id,
            "ticker": record.ticker,
            "topic": record.topic,
            "title": record.title,
            "publisher": record.publisher,
            "source_url": record.source_url,
            "source_type": record.source_type,
            "published_at": record.published_at,
            "claim": record.claim,
            "polarity": record.polarity,
        }
        for key, value in required_text_fields.items():
            if not value:
                raise EvidenceValidationError(f"Missing required field: {key}")

        if record.source_type not in self.ALLOWED_SOURCE_TYPES:
            raise EvidenceValidationError(f"Unsupported source_type: {record.source_type}")
        if record.polarity not in self.ALLOWED_POLARITIES:
            raise EvidenceValidationError(f"Unsupported polarity: {record.polarity}")
        if not (record.source_url.startswith("http://") or record.source_url.startswith("https://")):
            raise EvidenceValidationError("Evidence URL must be public http(s)")

        published_dt = self._parse_iso(record.published_at)
        as_of_dt = self._parse_iso(as_of)
        if published_dt > as_of_dt:
            raise EvidenceValidationError("Evidence published_at cannot be after as_of")

        if not (0.0 <= record.confidence_hint <= 1.0):
            raise EvidenceValidationError("confidence_hint must be between 0 and 1")

        if "source_document_id" not in record.provenance:
            raise EvidenceValidationError("provenance.source_document_id is required")

        return record

    def _deduplicate(
        self, records: tuple[NormalizedEvidenceRecord, ...]
    ) -> tuple[tuple[NormalizedEvidenceRecord, ...], dict[str, tuple[str, ...]]]:
        by_fingerprint: dict[str, list[NormalizedEvidenceRecord]] = {}
        for record in records:
            by_fingerprint.setdefault(record.fingerprint, []).append(record)

        deduped: list[NormalizedEvidenceRecord] = []
        duplicate_map: dict[str, tuple[str, ...]] = {}
        for fingerprint in sorted(by_fingerprint):
            group = sorted(by_fingerprint[fingerprint], key=lambda row: row.evidence_id)
            canonical = group[0]
            deduped.append(canonical)
            duplicate_map[canonical.evidence_id] = tuple(item.evidence_id for item in group[1:])

        return tuple(deduped), duplicate_map

    def _score(self, *, as_of: str, records: tuple[NormalizedEvidenceRecord, ...]) -> dict[str, float]:
        as_of_dt = self._parse_iso(as_of)
        corroboration_counts: dict[tuple[str, str], int] = {}
        for row in records:
            key = (row.topic, row.polarity)
            corroboration_counts[key] = corroboration_counts.get(key, 0) + 1

        source_weights = {
            "filing": 1.00,
            "transcript": 0.90,
            "research": 0.80,
            "industry": 0.75,
            "news": 0.65,
            "macro": 0.70,
        }

        scores: dict[str, float] = {}
        for row in records:
            age_days = max(0, (as_of_dt - self._parse_iso(row.published_at)).days)
            recency_weight = 1.0 / (1.0 + age_days / 365.0)
            corroboration_weight = min(1.0, corroboration_counts[(row.topic, row.polarity)] / 3.0)
            score = round(
                (0.55 * source_weights[row.source_type])
                + (0.20 * recency_weight)
                + (0.15 * row.confidence_hint)
                + (0.10 * corroboration_weight),
                6,
            )
            scores[row.evidence_id] = score
        return dict(sorted(scores.items()))

    def _summarize(
        self,
        *,
        ticker: str,
        as_of: str,
        records: tuple[NormalizedEvidenceRecord, ...],
        scores: dict[str, float],
    ) -> EvidenceConclusion:
        by_topic: dict[str, list[NormalizedEvidenceRecord]] = {}
        for row in records:
            if row.ticker != ticker:
                continue
            by_topic.setdefault(row.topic, []).append(row)

        fail_reasons: list[str] = []
        summaries: list[EvidenceSummary] = []
        unresolved_conflicts: list[str] = []

        missing_topics = sorted(topic for topic in self.REQUIRED_TOPICS if topic not in by_topic)
        if missing_topics:
            fail_reasons.append("MISSING_REQUIRED_TOPICS:" + ",".join(missing_topics))

        for topic in sorted(by_topic):
            topic_rows = sorted(by_topic[topic], key=lambda row: row.evidence_id)
            support_ids = tuple(row.evidence_id for row in topic_rows if row.polarity == "support")
            oppose_ids = tuple(row.evidence_id for row in topic_rows if row.polarity == "oppose")
            neutral_ids = tuple(row.evidence_id for row in topic_rows if row.polarity == "neutral")

            support_score = round(sum(scores[eid] for eid in support_ids), 6)
            oppose_score = round(sum(scores[eid] for eid in oppose_ids), 6)
            neutral_score = round(sum(scores[eid] for eid in neutral_ids), 6)

            if support_ids and oppose_ids:
                unresolved_conflicts.append(topic)

            if support_score > oppose_score:
                status = "supportive"
            elif oppose_score > support_score:
                status = "adverse"
            else:
                status = "inconclusive"

            confidence = round(max(support_score, oppose_score, neutral_score), 6)
            rationale = (
                f"support={len(support_ids)} oppose={len(oppose_ids)} "
                f"neutral={len(neutral_ids)}"
            )
            summaries.append(
                EvidenceSummary(
                    topic=topic,
                    supporting_evidence_ids=support_ids,
                    opposing_evidence_ids=oppose_ids,
                    neutral_evidence_ids=neutral_ids,
                    support_score=support_score,
                    oppose_score=oppose_score,
                    confidence=confidence,
                    status=status,
                    rationale=rationale,
                )
            )

        if not summaries:
            fail_reasons.append("NO_VALID_EVIDENCE_FOR_TICKER")

        if unresolved_conflicts:
            fail_reasons.append("UNRESOLVED_CONFLICTS:" + ",".join(sorted(unresolved_conflicts)))

        fail_closed = bool(fail_reasons)
        return EvidenceConclusion(
            ticker=ticker,
            as_of=as_of,
            summaries=tuple(summaries),
            unresolved_conflict_topics=tuple(sorted(set(unresolved_conflicts))),
            fail_closed=fail_closed,
            fail_reasons=tuple(sorted(set(fail_reasons))),
        )

    @staticmethod
    def _fingerprint(
        *, ticker: str, topic: str, title: str, publisher: str, source_url: str, published_at: str, claim: str
    ) -> str:
        payload = {
            "ticker": ticker,
            "topic": topic,
            "title": title,
            "publisher": publisher,
            "source_url": source_url,
            "published_at": published_at,
            "claim": claim,
        }
        canonical = str(sorted(payload.items()))
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)

    @staticmethod
    def to_canonical_json(result: EvidenceEngineResult) -> dict[str, object]:
        return {
            "passed": result.passed,
            "counts": {
                "collected": result.collected_count,
                "normalized": result.normalized_count,
                "validated": result.validated_count,
                "deduplicated": result.deduplicated_count,
            },
            "duplicate_map": dict(sorted(result.duplicate_map.items())),
            "evidence_scores": dict(sorted(result.evidence_scores.items())),
            "evidence_by_id": {
                key: asdict(value)
                for key, value in sorted(result.evidence_by_id.items(), key=lambda item: item[0])
            },
            "conclusion": asdict(result.conclusion),
            "audit_steps": list(result.audit_steps),
        }
