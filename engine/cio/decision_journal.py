from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from .decision_record import (
    DecisionJournalConflictError,
    DecisionJournalError,
    DecisionJournalMissingRecordError,
    DecisionRecord,
    build_decision_id,
)
from .outcome_reconciliation import RealizedOutcome, confidence_bucket_from_confidence
from .models import ActionRecommendation, DailyCIOBrief, MaterialNewsItem, ThesisChange


DEFAULT_ROOT = Path("artifacts") / "cio" / "decision_journal"


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _stable_lines(payloads: Iterable[dict[str, Any]]) -> list[str]:
    return [_stable_json(payload) for payload in payloads]


def _jsonl_text(lines: Iterable[str]) -> str:
    return "\n".join(lines) + ("\n" if lines else "")


def _first_sentence(text: str) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return ""
    return value.split(". ", 1)[0].strip()


class DecisionJournal:
    def __init__(self, root_path: Path = DEFAULT_ROOT) -> None:
        self.root_path = Path(root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.decisions_path = self.root_path / "decisions.jsonl"
        self.outcomes_path = self.root_path / "outcomes.jsonl"
        self.index_path = self.root_path / "index.json"
        self.summary_path = self.root_path / "performance_summary.json"
        self.report_path = self.root_path / "performance_report.md"

    def record_brief(self, brief: DailyCIOBrief) -> tuple[DecisionRecord, ...]:
        source_brief_id = self._source_brief_id(brief)
        candidates = self._records_from_brief(brief, source_brief_id=source_brief_id)
        written: list[DecisionRecord] = []
        for record in candidates:
            stored = self._append_or_validate_decision(record)
            written.append(stored)
        self._write_index()
        return tuple(written)

    def record_outcome(self, outcome: RealizedOutcome) -> RealizedOutcome:
        decision_id = str(getattr(outcome, "decision_id", "") or "").strip()
        if not decision_id:
            open_records = self._load_decision_records()
            if len(open_records) == 1:
                decision_id = open_records[0].decision_id
                outcome = RealizedOutcome(
                    absolute_return=outcome.absolute_return,
                    benchmark_adjusted_return=outcome.benchmark_adjusted_return,
                    directionally_correct=outcome.directionally_correct,
                    confidence_bucket=outcome.confidence_bucket,
                    thesis_outcome=outcome.thesis_outcome,
                    evaluation_date=outcome.evaluation_date,
                    notes=outcome.notes,
                    decision_id=decision_id,
                )
            else:
                raise DecisionJournalError("Outcome must include decision_id when more than one decision exists.")

        decisions = {record.decision_id for record in self._load_decision_records()}
        if decision_id not in decisions:
            raise DecisionJournalMissingRecordError(f"Unknown decision_id: {decision_id}")

        stored = self._append_or_validate_outcome(outcome)
        self._write_index()
        return stored

    def generate_performance_summary(self) -> dict[str, Any]:
        decisions = self._load_decision_records()
        outcomes = self._load_outcomes()
        outcome_map = {outcome.decision_id: outcome for outcome in outcomes}

        closed_records = [record for record in decisions if record.decision_id in outcome_map]
        open_records = [record for record in decisions if record.decision_id not in outcome_map]

        summary = self._build_performance_summary(decisions, closed_records, open_records, outcome_map)
        self.summary_path.write_text(_stable_json(summary) + "\n", encoding="utf-8")
        self.report_path.write_text(self._render_performance_report(summary), encoding="utf-8")
        self._write_index()
        return summary

    def _records_from_brief(self, brief: DailyCIOBrief, *, source_brief_id: str) -> tuple[DecisionRecord, ...]:
        candidates: list[tuple[str, DecisionRecord]] = []

        for ordinal, action in enumerate(brief.top_actions, start=1):
            candidates.append((
                self._decision_key(brief.date, action.symbol, action.action_type, action.reason, source_brief_id),
                self._build_record_from_action(
                    brief=brief,
                    action=action,
                    source_brief_id=source_brief_id,
                    section_name="top_actions",
                    ordinal=ordinal,
                    symbol_override=action.symbol,
                    recommendation_override=None,
                ),
            ))

        for ordinal, action in enumerate(brief.recommended_buys, start=1):
            candidates.append((
                self._decision_key(brief.date, action.symbol, action.action_type, action.reason, source_brief_id),
                self._build_record_from_action(
                    brief=brief,
                    action=action,
                    source_brief_id=source_brief_id,
                    section_name="recommended_buys",
                    ordinal=ordinal,
                    symbol_override=action.symbol,
                    recommendation_override=None,
                ),
            ))

        for ordinal, action in enumerate(brief.recommended_trims, start=1):
            candidates.append((
                self._decision_key(brief.date, action.symbol, action.action_type, action.reason, source_brief_id),
                self._build_record_from_action(
                    brief=brief,
                    action=action,
                    source_brief_id=source_brief_id,
                    section_name="recommended_trims",
                    ordinal=ordinal,
                    symbol_override=action.symbol,
                    recommendation_override=None,
                ),
            ))

        if self._cash_actionable(brief.cash_recommendation):
            cash_action = ActionRecommendation(
                priority=len(candidates) + 1,
                title="Cash Recommendation",
                reason=_first_sentence(brief.cash_recommendation) or brief.cash_recommendation,
                expected_benefit=brief.cash_recommendation,
                confidence=brief.confidence_score,
                supporting_evidence=(brief.executive_summary,),
                symbol="CASH",
                action_type="cash",
            )
            candidates.append((
                self._decision_key(brief.date, "CASH", "cash", brief.cash_recommendation, source_brief_id),
                self._build_record_from_action(
                    brief=brief,
                    action=cash_action,
                    source_brief_id=source_brief_id,
                    section_name="cash_recommendation",
                    ordinal=1,
                    symbol_override="CASH",
                    recommendation_override=brief.cash_recommendation,
                ),
            ))

        ordered: list[DecisionRecord] = []
        seen: set[str] = set()
        for decision_key, record in candidates:
            if decision_key in seen:
                continue
            seen.add(decision_key)
            ordered.append(record)

        canonical = [
            DecisionRecord(
                decision_id=record.decision_id,
                created_at=record.created_at,
                as_of_date=record.as_of_date,
                symbol=record.symbol,
                action_type=record.action_type,
                priority=index + 1,
                recommendation=record.recommendation,
                confidence=record.confidence,
                expected_benefit=record.expected_benefit,
                expected_risk=record.expected_risk,
                supporting_evidence=record.supporting_evidence,
                conflicting_evidence=record.conflicting_evidence,
                assumptions=record.assumptions,
                invalidation_conditions=record.invalidation_conditions,
                source_brief_id=record.source_brief_id,
                status=record.status,
                realized_outcome=record.realized_outcome,
            )
            for index, record in enumerate(ordered)
        ]
        return tuple(canonical)

    def _build_record_from_action(
        self,
        *,
        brief: DailyCIOBrief,
        action: ActionRecommendation,
        source_brief_id: str,
        section_name: str,
        ordinal: int,
        symbol_override: str,
        recommendation_override: str | None,
    ) -> DecisionRecord:
        symbol = symbol_override.strip().upper()
        action_type = action.action_type.strip().lower() or "hold"
        recommendation = recommendation_override or f"{action.title}: {action.reason}"
        decision_id = self._decision_key(brief.date, symbol, action_type, recommendation, source_brief_id)
        supporting, conflicting = self._evidence_by_symbol(brief, symbol=symbol, action_type=action_type, supporting=action.supporting_evidence)
        assumptions, invalidation = self._action_contract(action_type=action_type, symbol=symbol, brief=brief, section_name=section_name)
        expected_risk = self._expected_risk_text(action_type=action_type, symbol=symbol, brief=brief)
        created_at = f"{brief.date}T00:00:00+00:00"
        return DecisionRecord(
            decision_id=decision_id,
            created_at=created_at,
            as_of_date=brief.date,
            symbol=symbol,
            action_type=action_type,
            priority=ordinal,
            recommendation=recommendation,
            confidence=round(float(action.confidence), 2),
            expected_benefit=action.expected_benefit,
            expected_risk=expected_risk,
            supporting_evidence=supporting,
            conflicting_evidence=conflicting,
            assumptions=assumptions,
            invalidation_conditions=invalidation,
            source_brief_id=source_brief_id,
            status="OPEN",
            realized_outcome=None,
        )

    def _expected_risk_text(self, *, action_type: str, symbol: str, brief: DailyCIOBrief) -> str:
        risk_map = {
            "buy": f"{symbol} could underperform if the catalyst stalls or the thesis weakens.",
            "trim": f"{symbol} may continue to appreciate after de-risking.",
            "hold": f"{symbol} may drift without a decisive catalyst.",
            "cash": f"Idle cash can lag if the market advances while risk remains contained.",
        }
        return risk_map.get(action_type, f"{symbol} recommendation carries normal execution and thesis risk.")

    def _action_contract(self, *, action_type: str, symbol: str, brief: DailyCIOBrief, section_name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if action_type == "buy":
            assumptions = (
                f"{symbol} remains supported by current valuation and conviction scores.",
                f"{symbol} material news remains net supportive or neutral.",
            )
            invalidation = (
                f"{symbol} thesis deteriorates materially.",
                f"New negative material news undercuts the buy case.",
            )
        elif action_type == "trim":
            assumptions = (
                f"{symbol} remains concentrated or risk elevated relative to portfolio constraints.",
                f"The brief still prefers de-risking over adding exposure.",
            )
            invalidation = (
                f"{symbol} risk normalizes or concentration drops below target.",
                f"Material news materially improves the holding thesis.",
            )
        elif action_type == "cash":
            assumptions = (
                "Cash deployment should preserve optionality.",
                "The current brief prefers capital preservation before redeployment.",
            )
            invalidation = (
                "A higher-conviction deployment opportunity appears.",
                "Portfolio risk falls enough to justify redeployment.",
            )
        else:
            assumptions = (
                f"{symbol} remains balanced under the current brief.",
                f"{section_name} continues to support a neutral posture.",
            )
            invalidation = (
                f"{symbol} sees a decisive thesis break.",
                f"A stronger opposing catalyst changes the stance.",
            )
        return assumptions, invalidation

    def _evidence_by_symbol(
        self,
        brief: DailyCIOBrief,
        *,
        symbol: str,
        action_type: str,
        supporting: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        material_news = [item for item in brief.material_news if item.symbol.upper() == symbol]
        thesis_changes = [change for change in brief.thesis_changes if change.symbol.upper() == symbol]

        supportive_news: list[str] = []
        conflicting_news: list[str] = []
        if action_type == "buy":
            supportive_news = [f"{item.headline} ({item.impact})" for item in material_news if item.impact.strip().lower() == "positive"]
            conflicting_news = [f"{item.headline} ({item.impact})" for item in material_news if item.impact.strip().lower() == "negative"]
        elif action_type == "trim":
            supportive_news = [f"{item.headline} ({item.impact})" for item in material_news if item.impact.strip().lower() == "negative"]
            conflicting_news = [f"{item.headline} ({item.impact})" for item in material_news if item.impact.strip().lower() == "positive"]
        elif action_type == "cash":
            supportive_news = [f"{item.headline} ({item.impact})" for item in material_news]
        else:
            supportive_news = [f"{item.headline} ({item.impact})" for item in material_news]

        thesis_support = []
        thesis_conflict = []
        for change in thesis_changes:
            change_text = f"Thesis {change.previous_score:.1f}->{change.adjusted_score:.1f} ({change.delta:+.1f})"
            if action_type == "buy" and change.delta >= 0:
                thesis_support.append(change_text)
            elif action_type == "trim" and change.delta <= 0:
                thesis_support.append(change_text)
            elif action_type == "cash":
                thesis_support.append(change_text)
            else:
                thesis_conflict.append(change_text)

        support = tuple(dict.fromkeys(tuple(supporting) + tuple(supportive_news) + tuple(thesis_support)))
        conflict = tuple(dict.fromkeys(tuple(conflicting_news) + tuple(thesis_conflict)))
        return support, conflict

    def _append_or_validate_decision(self, record: DecisionRecord) -> DecisionRecord:
        existing = self._load_decision_records()
        for prior in existing:
            if prior.decision_id != record.decision_id:
                continue
            if prior.to_json_line() == record.to_json_line():
                return prior
            raise DecisionJournalConflictError(f"Conflicting decision_id: {record.decision_id}")

        with self.decisions_path.open("a", encoding="utf-8") as handle:
            handle.write(record.to_json_line() + "\n")
        return record

    def _append_or_validate_outcome(self, outcome: RealizedOutcome) -> RealizedOutcome:
        existing = self._load_outcomes()
        for prior in existing:
            if prior.decision_id != outcome.decision_id:
                continue
            if prior.to_dict() == outcome.to_dict():
                return prior
            raise DecisionJournalConflictError(f"Conflicting outcome decision_id: {outcome.decision_id}")

        with self.outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(_stable_json(outcome.to_dict()) + "\n")
        return outcome

    def _load_decision_records(self) -> list[DecisionRecord]:
        if not self.decisions_path.exists():
            return []
        records: list[DecisionRecord] = []
        for line in self.decisions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(DecisionRecord.from_dict(json.loads(line)))
        return records

    def _load_outcomes(self) -> list[RealizedOutcome]:
        if not self.outcomes_path.exists():
            return []
        outcomes: list[RealizedOutcome] = []
        for line in self.outcomes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            outcomes.append(RealizedOutcome.from_dict(json.loads(line)))
        return outcomes

    def _write_index(self) -> dict[str, Any]:
        decisions = self._load_decision_records()
        outcomes = self._load_outcomes()
        summary = self._build_index_payload(decisions, outcomes)
        self.index_path.write_text(_stable_json(summary) + "\n", encoding="utf-8")
        return summary

    def _build_index_payload(self, decisions: list[DecisionRecord], outcomes: list[RealizedOutcome]) -> dict[str, Any]:
        outcome_ids = {outcome.decision_id for outcome in outcomes}
        latest_as_of_date = max((record.as_of_date for record in decisions), default="")
        payload = {
            "total_records": len(decisions),
            "open_records": sum(1 for record in decisions if record.decision_id not in outcome_ids),
            "closed_records": sum(1 for record in decisions if record.decision_id in outcome_ids),
            "records_by_action_type": self._count_by(decisions, key=lambda record: record.action_type),
            "records_by_symbol": self._count_by(decisions, key=lambda record: record.symbol),
            "latest_as_of_date": latest_as_of_date,
        }
        payload["content_hash"] = self._content_hash(decisions, outcomes)
        return payload

    def _build_performance_summary(
        self,
        decisions: list[DecisionRecord],
        closed_records: list[DecisionRecord],
        open_records: list[DecisionRecord],
        outcome_map: dict[str, RealizedOutcome],
    ) -> dict[str, Any]:
        recommendation_count = len(decisions)
        closed_count = len(closed_records)
        open_count = len(open_records)
        if closed_count:
            win_rate = round(sum(1 for record in closed_records if outcome_map[record.decision_id].benchmark_adjusted_return > 0) / closed_count, 6)
            directional_accuracy = round(sum(1 for record in closed_records if outcome_map[record.decision_id].directionally_correct) / closed_count, 6)
            average_return = round(sum(outcome_map[record.decision_id].absolute_return for record in closed_records) / closed_count, 6)
            average_benchmark_adjusted_return = round(sum(outcome_map[record.decision_id].benchmark_adjusted_return for record in closed_records) / closed_count, 6)
        else:
            win_rate = directional_accuracy = average_return = average_benchmark_adjusted_return = 0.0

        action_type_payload = {}
        for action_type, group in self._group_by(decisions, key=lambda record: record.action_type).items():
            closed_group = [record for record in group if record.decision_id in outcome_map]
            action_type_payload[action_type] = self._group_metrics(closed_group, outcome_map)

        confidence_bucket_payload = {}
        for bucket, group in self._group_by(decisions, key=lambda record: confidence_bucket_from_confidence(record.confidence)).items():
            closed_group = [record for record in group if record.decision_id in outcome_map]
            confidence_bucket_payload[bucket] = self._group_metrics(closed_group, outcome_map)

        summary = {
            "recommendation_count": recommendation_count,
            "win_rate": win_rate,
            "directional_accuracy": directional_accuracy,
            "average_return": average_return,
            "average_benchmark_adjusted_return": average_benchmark_adjusted_return,
            "results_by_action_type": dict(sorted(action_type_payload.items())),
            "results_by_confidence_bucket": self._ordered_bucket_results(confidence_bucket_payload),
            "open_decision_count": open_count,
            "closed_decision_count": closed_count,
            "latest_as_of_date": max((record.as_of_date for record in decisions), default=""),
            "content_hash": self._content_hash(decisions, list(outcome_map.values())),
        }
        return summary

    def _group_metrics(self, records: list[DecisionRecord], outcome_map: dict[str, RealizedOutcome]) -> dict[str, Any]:
        if not records:
            return {
                "count": 0,
                "win_rate": 0.0,
                "directional_accuracy": 0.0,
                "average_return": 0.0,
                "average_benchmark_adjusted_return": 0.0,
            }
        count = len(records)
        win_rate = round(sum(1 for record in records if outcome_map[record.decision_id].benchmark_adjusted_return > 0) / count, 6)
        directional_accuracy = round(sum(1 for record in records if outcome_map[record.decision_id].directionally_correct) / count, 6)
        average_return = round(sum(outcome_map[record.decision_id].absolute_return for record in records) / count, 6)
        average_benchmark_adjusted_return = round(sum(outcome_map[record.decision_id].benchmark_adjusted_return for record in records) / count, 6)
        return {
            "count": count,
            "win_rate": win_rate,
            "directional_accuracy": directional_accuracy,
            "average_return": average_return,
            "average_benchmark_adjusted_return": average_benchmark_adjusted_return,
        }

    @staticmethod
    def _ordered_bucket_results(payload: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CONVICTION": 3}
        return dict(sorted(payload.items(), key=lambda item: order.get(item[0], 99)))

    @staticmethod
    def _count_by(records: list[DecisionRecord], *, key) -> dict[str, int]:
        counter = Counter(key(record) for record in records)
        return dict(sorted(counter.items(), key=lambda item: item[0]))

    @staticmethod
    def _group_by(records: list[DecisionRecord], *, key) -> dict[str, list[DecisionRecord]]:
        grouped: dict[str, list[DecisionRecord]] = defaultdict(list)
        for record in records:
            grouped[key(record)].append(record)
        return dict(sorted(grouped.items(), key=lambda item: item[0]))

    @staticmethod
    def _content_hash(decisions: list[DecisionRecord], outcomes: list[RealizedOutcome]) -> str:
        payload = {
            "decisions": [record.to_dict() for record in decisions],
            "outcomes": [outcome.to_dict() for outcome in outcomes],
        }
        return sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _decision_key(as_of_date: str, symbol: str, action_type: str, recommendation: str, source_brief_id: str) -> str:
        return build_decision_id(
            as_of_date=as_of_date,
            symbol=symbol,
            action_type=action_type,
            recommendation=recommendation,
            source_brief_id=source_brief_id,
        )

    @staticmethod
    def _cash_actionable(cash_recommendation: str) -> bool:
        text = str(cash_recommendation or "").strip().lower()
        if not text:
            return False
        return not text.startswith(("maintain", "hold", "no action", "none"))

    @staticmethod
    def _source_brief_id(brief: DailyCIOBrief) -> str:
        payload = asdict(brief)
        return "BRIEF-" + sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:20].upper()

    @staticmethod
    def _render_performance_report(summary: dict[str, Any]) -> str:
        lines = [
            "# Decision Journal Performance Report",
            "",
            f"Recommendation count: {summary['recommendation_count']}",
            f"Open decisions: {summary['open_decision_count']}",
            f"Closed decisions: {summary['closed_decision_count']}",
            f"Win rate: {summary['win_rate']:.6f}",
            f"Directional accuracy: {summary['directional_accuracy']:.6f}",
            f"Average return: {summary['average_return']:.6f}",
            f"Average benchmark-adjusted return: {summary['average_benchmark_adjusted_return']:.6f}",
            "",
            "## Results By Action Type",
            "| Action Type | Count | Win Rate | Directional Accuracy | Average Return | Avg Benchmark Adjusted Return |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for action_type, stats in summary["results_by_action_type"].items():
            lines.append(
                f"| {action_type} | {stats['count']} | {stats['win_rate']:.6f} | {stats['directional_accuracy']:.6f} | {stats['average_return']:.6f} | {stats['average_benchmark_adjusted_return']:.6f} |"
            )
        lines.extend([
            "",
            "## Results By Confidence Bucket",
            "| Bucket | Count | Win Rate | Directional Accuracy | Average Return | Avg Benchmark Adjusted Return |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for bucket, stats in summary["results_by_confidence_bucket"].items():
            lines.append(
                f"| {bucket} | {stats['count']} | {stats['win_rate']:.6f} | {stats['directional_accuracy']:.6f} | {stats['average_return']:.6f} | {stats['average_benchmark_adjusted_return']:.6f} |"
            )
        lines.extend([
            "",
            "## Notes",
            "- This report is deterministic and derived only from journal records and explicit reconciliations.",
            "- No broker access or external market data was used.",
        ])
        return "\n".join(lines) + "\n"