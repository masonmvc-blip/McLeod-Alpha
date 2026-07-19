from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from tempfile import TemporaryDirectory
from typing import Any

from .daily_brief import render_daily_cio_brief
from .decision_engine import DecisionEngine
from .decision_journal import DecisionJournal
from .learning_report import PerformanceReport
from .models import (
    DecisionEngineInputs,
    MaterialNewsItem,
    PortfolioConstraint,
    PortfolioHolding,
    WatchlistItem,
)
from .outcome_reconciliation import RealizedOutcome
from .performance_lab import PerformanceLab, PerformanceLabInputs
from .portfolio_os import PortfolioOS
from .portfolio_plan import PortfolioOSInputs, PortfolioPlan, render_portfolio_plan


SCHEMA_VERSION = "1.0.0"


class CIOPipelineError(RuntimeError):
    pass


class CIOPipelineValidationError(CIOPipelineError):
    pass


class CIOPipelineConflictError(CIOPipelineError):
    pass


@dataclass(frozen=True)
class StageStatus:
    stage: str
    status: str
    blocker: str = ""


@dataclass(frozen=True)
class CIOPipelineInputs:
    decision_engine_inputs: DecisionEngineInputs
    journal_root: Path
    portfolio_os_settings: dict[str, Any]
    realized_outcomes: tuple[RealizedOutcome, ...]
    output_root: Path
    input_hash: str
    normalized_payload: dict[str, Any]


@dataclass(frozen=True)
class CIOPipelineResult:
    run_id: str
    as_of_date: str
    decision_brief: Any | None
    decision_records: tuple[Any, ...]
    portfolio_plan: PortfolioPlan | None
    performance_report: PerformanceReport | None
    artifact_paths: tuple[str, ...]
    stage_statuses: tuple[StageStatus, ...]
    overall_status: str
    content_hash: str


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _hash_text(content: str) -> str:
    return _hash_bytes(content.encode("utf-8"))


def _content_hash_for_mapping(payload: dict[str, str]) -> str:
    return _hash_text(_stable_json(payload))


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _atomic_write_text(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def _required_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise CIOPipelineValidationError(f"{label} missing required keys: {', '.join(sorted(missing))}")


def _as_float(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CIOPipelineValidationError(f"{label} must be numeric") from exc


def _as_str(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CIOPipelineValidationError(f"{label} must be a non-empty string")
    return text


def _as_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CIOPipelineValidationError(f"{label} must be an object")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CIOPipelineValidationError(f"{label} must be an array")
    return value


def _normalize_top_level_payload(raw_payload: dict[str, Any], *, output_root_override: str | None) -> dict[str, Any]:
    required = (
        "decision_engine_inputs",
        "journal_root",
        "portfolio_os_settings",
        "realized_outcomes",
        "output_root",
    )
    _required_keys(raw_payload, required, "pipeline input")
    extra_keys = set(raw_payload) - set(required)
    if extra_keys:
        raise CIOPipelineValidationError(f"pipeline input has unexpected keys: {', '.join(sorted(extra_keys))}")

    payload = dict(raw_payload)
    if output_root_override:
        payload["output_root"] = output_root_override
    return payload


def _parse_holdings(payload: list[dict[str, Any]]) -> tuple[PortfolioHolding, ...]:
    holdings: list[PortfolioHolding] = []
    for index, item in enumerate(payload):
        row = _as_dict(item, f"decision_engine_inputs.holdings[{index}]")
        _required_keys(row, ("symbol", "quantity", "market_value"), f"decision_engine_inputs.holdings[{index}]")
        holdings.append(
            PortfolioHolding(
                symbol=_as_str(row.get("symbol"), f"decision_engine_inputs.holdings[{index}].symbol"),
                quantity=_as_float(row.get("quantity"), f"decision_engine_inputs.holdings[{index}].quantity"),
                market_value=_as_float(row.get("market_value"), f"decision_engine_inputs.holdings[{index}].market_value"),
                sector=str(row.get("sector", "Unknown")),
                thesis_health_score=_as_float(row.get("thesis_health_score", 50.0), f"decision_engine_inputs.holdings[{index}].thesis_health_score"),
                valuation_score=_as_float(row.get("valuation_score", 50.0), f"decision_engine_inputs.holdings[{index}].valuation_score"),
                conviction_score=_as_float(row.get("conviction_score", 50.0), f"decision_engine_inputs.holdings[{index}].conviction_score"),
                risk_score=_as_float(row.get("risk_score", 50.0), f"decision_engine_inputs.holdings[{index}].risk_score"),
                liquidity_score=_as_float(row.get("liquidity_score", 50.0), f"decision_engine_inputs.holdings[{index}].liquidity_score"),
                notes=str(row.get("notes", "")),
            )
        )
    return tuple(holdings)


def _parse_watchlist(payload: list[dict[str, Any]]) -> tuple[WatchlistItem, ...]:
    watchlist: list[WatchlistItem] = []
    for index, item in enumerate(payload):
        row = _as_dict(item, f"decision_engine_inputs.watchlist[{index}]")
        _required_keys(
            row,
            ("symbol", "thesis", "valuation_score", "conviction_score", "risk_score"),
            f"decision_engine_inputs.watchlist[{index}]",
        )
        watchlist.append(
            WatchlistItem(
                symbol=_as_str(row.get("symbol"), f"decision_engine_inputs.watchlist[{index}].symbol"),
                thesis=_as_str(row.get("thesis"), f"decision_engine_inputs.watchlist[{index}].thesis"),
                valuation_score=_as_float(row.get("valuation_score"), f"decision_engine_inputs.watchlist[{index}].valuation_score"),
                conviction_score=_as_float(row.get("conviction_score"), f"decision_engine_inputs.watchlist[{index}].conviction_score"),
                risk_score=_as_float(row.get("risk_score"), f"decision_engine_inputs.watchlist[{index}].risk_score"),
                sector=str(row.get("sector", "Unknown")),
                notes=str(row.get("notes", "")),
            )
        )
    return tuple(watchlist)


def _parse_material_news(payload: list[dict[str, Any]]) -> tuple[MaterialNewsItem, ...]:
    news_items: list[MaterialNewsItem] = []
    for index, item in enumerate(payload):
        row = _as_dict(item, f"decision_engine_inputs.recent_material_news[{index}]")
        _required_keys(
            row,
            ("symbol", "headline", "summary", "impact", "materiality_score", "source"),
            f"decision_engine_inputs.recent_material_news[{index}]",
        )
        news_items.append(
            MaterialNewsItem(
                symbol=_as_str(row.get("symbol"), f"decision_engine_inputs.recent_material_news[{index}].symbol"),
                headline=_as_str(row.get("headline"), f"decision_engine_inputs.recent_material_news[{index}].headline"),
                summary=_as_str(row.get("summary"), f"decision_engine_inputs.recent_material_news[{index}].summary"),
                impact=_as_str(row.get("impact"), f"decision_engine_inputs.recent_material_news[{index}].impact"),
                materiality_score=_as_float(row.get("materiality_score"), f"decision_engine_inputs.recent_material_news[{index}].materiality_score"),
                source=_as_str(row.get("source"), f"decision_engine_inputs.recent_material_news[{index}].source"),
                published_at=str(row.get("published_at", "")),
            )
        )
    return tuple(news_items)


def _parse_constraints(payload: dict[str, Any]) -> PortfolioConstraint:
    row = _as_dict(payload, "decision_engine_inputs.constraints")
    return PortfolioConstraint(
        min_cash_weight=_as_float(row.get("min_cash_weight", 0.10), "decision_engine_inputs.constraints.min_cash_weight"),
        target_cash_weight=_as_float(row.get("target_cash_weight", 0.15), "decision_engine_inputs.constraints.target_cash_weight"),
        max_single_name_weight=_as_float(row.get("max_single_name_weight", 0.25), "decision_engine_inputs.constraints.max_single_name_weight"),
        max_sector_weight=_as_float(row.get("max_sector_weight", 0.35), "decision_engine_inputs.constraints.max_sector_weight"),
        max_portfolio_risk=_as_float(row.get("max_portfolio_risk", 60.0), "decision_engine_inputs.constraints.max_portfolio_risk"),
        min_diversification_score=_as_float(row.get("min_diversification_score", 55.0), "decision_engine_inputs.constraints.min_diversification_score"),
        min_liquidity_score=_as_float(row.get("min_liquidity_score", 40.0), "decision_engine_inputs.constraints.min_liquidity_score"),
    )


def _parse_score_map(payload: Any, label: str) -> dict[str, float]:
    data = _as_dict(payload, label)
    normalized: dict[str, float] = {}
    for key, value in sorted(data.items(), key=lambda item: str(item[0])):
        normalized[str(key)] = _as_float(value, f"{label}.{key}")
    return normalized


def _parse_decision_engine_inputs(payload: dict[str, Any]) -> DecisionEngineInputs:
    row = _as_dict(payload, "decision_engine_inputs")
    _required_keys(
        row,
        (
            "date",
            "holdings",
            "cash_balance",
            "watchlist",
            "thesis_health_scores",
            "valuation_scores",
            "conviction_scores",
            "risk_scores",
            "recent_material_news",
            "constraints",
        ),
        "decision_engine_inputs",
    )
    return DecisionEngineInputs(
        date=_as_str(row.get("date"), "decision_engine_inputs.date"),
        holdings=_parse_holdings(_as_list(row.get("holdings"), "decision_engine_inputs.holdings")),
        cash_balance=_as_float(row.get("cash_balance"), "decision_engine_inputs.cash_balance"),
        watchlist=_parse_watchlist(_as_list(row.get("watchlist"), "decision_engine_inputs.watchlist")),
        thesis_health_scores=_parse_score_map(row.get("thesis_health_scores"), "decision_engine_inputs.thesis_health_scores"),
        valuation_scores=_parse_score_map(row.get("valuation_scores"), "decision_engine_inputs.valuation_scores"),
        conviction_scores=_parse_score_map(row.get("conviction_scores"), "decision_engine_inputs.conviction_scores"),
        risk_scores=_parse_score_map(row.get("risk_scores"), "decision_engine_inputs.risk_scores"),
        recent_material_news=_parse_material_news(_as_list(row.get("recent_material_news"), "decision_engine_inputs.recent_material_news")),
        constraints=_parse_constraints(row.get("constraints")),
    )


def _parse_portfolio_os_settings(payload: Any) -> dict[str, Any]:
    row = _as_dict(payload, "portfolio_os_settings")
    _required_keys(
        row,
        ("max_position_size", "min_position_size", "max_cash_allocation", "margin_settings"),
        "portfolio_os_settings",
    )
    margin_settings = _as_dict(row.get("margin_settings"), "portfolio_os_settings.margin_settings")
    return {
        "max_position_size": _as_float(row.get("max_position_size"), "portfolio_os_settings.max_position_size"),
        "min_position_size": _as_float(row.get("min_position_size"), "portfolio_os_settings.min_position_size"),
        "max_cash_allocation": _as_float(row.get("max_cash_allocation"), "portfolio_os_settings.max_cash_allocation"),
        "margin_settings": dict(sorted(((str(key), value) for key, value in margin_settings.items()), key=lambda item: item[0])),
    }


def _parse_realized_outcomes(payload: Any) -> tuple[RealizedOutcome, ...]:
    rows = _as_list(payload, "realized_outcomes")
    outcomes: list[RealizedOutcome] = []
    for index, item in enumerate(rows):
        row = _as_dict(item, f"realized_outcomes[{index}]")
        _required_keys(
            row,
            (
                "absolute_return",
                "benchmark_adjusted_return",
                "directionally_correct",
                "confidence_bucket",
                "thesis_outcome",
                "evaluation_date",
                "notes",
                "decision_id",
            ),
            f"realized_outcomes[{index}]",
        )
        notes = _as_list(row.get("notes"), f"realized_outcomes[{index}].notes")
        outcomes.append(
            RealizedOutcome(
                absolute_return=_as_float(row.get("absolute_return"), f"realized_outcomes[{index}].absolute_return"),
                benchmark_adjusted_return=_as_float(row.get("benchmark_adjusted_return"), f"realized_outcomes[{index}].benchmark_adjusted_return"),
                directionally_correct=bool(row.get("directionally_correct")),
                confidence_bucket=_as_str(row.get("confidence_bucket"), f"realized_outcomes[{index}].confidence_bucket"),
                thesis_outcome=_as_str(row.get("thesis_outcome"), f"realized_outcomes[{index}].thesis_outcome"),
                evaluation_date=_as_str(row.get("evaluation_date"), f"realized_outcomes[{index}].evaluation_date"),
                notes=tuple(str(note) for note in notes),
                decision_id=_as_str(row.get("decision_id"), f"realized_outcomes[{index}].decision_id"),
            )
        )
    return tuple(outcomes)


def load_pipeline_inputs(input_path: Path, *, output_root_override: str | None = None) -> CIOPipelineInputs:
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CIOPipelineValidationError(f"input file not found: {input_path}") from exc
    except json.JSONDecodeError as exc:
        raise CIOPipelineValidationError(f"input file is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise CIOPipelineValidationError("pipeline input JSON must be an object")

    payload = _normalize_top_level_payload(raw, output_root_override=output_root_override)
    decision_engine_inputs = _parse_decision_engine_inputs(payload.get("decision_engine_inputs"))
    journal_root = Path(_as_str(payload.get("journal_root"), "journal_root"))
    portfolio_os_settings = _parse_portfolio_os_settings(payload.get("portfolio_os_settings"))
    realized_outcomes = _parse_realized_outcomes(payload.get("realized_outcomes"))
    output_root = Path(_as_str(payload.get("output_root"), "output_root"))

    normalized_payload = {
        "decision_engine_inputs": {
            "date": decision_engine_inputs.date,
            "holdings": [holding.__dict__ for holding in decision_engine_inputs.holdings],
            "cash_balance": decision_engine_inputs.cash_balance,
            "watchlist": [item.__dict__ for item in decision_engine_inputs.watchlist],
            "thesis_health_scores": dict(sorted(decision_engine_inputs.thesis_health_scores.items(), key=lambda item: item[0])),
            "valuation_scores": dict(sorted(decision_engine_inputs.valuation_scores.items(), key=lambda item: item[0])),
            "conviction_scores": dict(sorted(decision_engine_inputs.conviction_scores.items(), key=lambda item: item[0])),
            "risk_scores": dict(sorted(decision_engine_inputs.risk_scores.items(), key=lambda item: item[0])),
            "recent_material_news": [item.__dict__ for item in decision_engine_inputs.recent_material_news],
            "constraints": decision_engine_inputs.constraints.__dict__,
        },
        "journal_root": str(journal_root),
        "portfolio_os_settings": portfolio_os_settings,
        "realized_outcomes": [outcome.to_dict() for outcome in realized_outcomes],
        "output_root": str(output_root),
    }
    input_hash = _hash_text(_stable_json(normalized_payload))

    return CIOPipelineInputs(
        decision_engine_inputs=decision_engine_inputs,
        journal_root=journal_root,
        portfolio_os_settings=portfolio_os_settings,
        realized_outcomes=realized_outcomes,
        output_root=output_root,
        input_hash=input_hash,
        normalized_payload=normalized_payload,
    )


def _build_run_id(input_hash: str) -> str:
    return "CIO-" + input_hash[:16].upper()


def _stage_statuses_for_failure(statuses: list[StageStatus], stage_names: tuple[str, ...], failed_stage: str, blocker: str) -> tuple[StageStatus, ...]:
    existing = {status.stage: status for status in statuses}
    finalized: list[StageStatus] = []
    failed_seen = False
    for stage in stage_names:
        if stage in existing:
            finalized.append(existing[stage])
            if existing[stage].status == "failed":
                failed_seen = True
            continue
        if not failed_seen:
            if stage == failed_stage:
                finalized.append(StageStatus(stage=stage, status="failed", blocker=blocker))
                failed_seen = True
            else:
                finalized.append(StageStatus(stage=stage, status="not_run", blocker=f"Blocked by {failed_stage}"))
        else:
            finalized.append(StageStatus(stage=stage, status="not_run", blocker=f"Blocked by {failed_stage}"))
    return tuple(finalized)


def _build_pipeline_summary_payload(
    *,
    run_id: str,
    as_of_date: str,
    artifact_directory: Path,
    stage_statuses: tuple[StageStatus, ...],
    overall_status: str,
    blocker: str,
    created_artifacts: tuple[str, ...],
    content_hash: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "as_of_date": as_of_date,
        "artifact_directory": str(artifact_directory),
        "overall_status": overall_status,
        "stage_statuses": [status.__dict__ for status in stage_statuses],
        "first_blocker": blocker,
        "created_artifacts": list(created_artifacts),
        "content_hash": content_hash,
    }


def _stage_payload_hashes(artifact_contents: dict[str, bytes]) -> dict[str, str]:
    return {name: _hash_bytes(content) for name, content in sorted(artifact_contents.items(), key=lambda item: item[0])}


def _check_existing_artifacts(artifact_dir: Path, artifact_contents: dict[str, bytes]) -> None:
    for name, expected in sorted(artifact_contents.items(), key=lambda item: item[0]):
        path = artifact_dir / name
        if not path.exists():
            raise CIOPipelineConflictError(f"Existing run directory missing expected artifact: {name}")
        observed = path.read_bytes()
        if observed != expected:
            raise CIOPipelineConflictError(f"Artifact conflict for {name}")


def _write_new_artifacts(artifact_dir: Path, artifact_contents: dict[str, bytes]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, content in sorted(artifact_contents.items(), key=lambda item: item[0]):
        _atomic_write_bytes(artifact_dir / name, content)


def run_cio_pipeline(inputs: CIOPipelineInputs, *, validate_only: bool = False) -> CIOPipelineResult:
    run_id = _build_run_id(inputs.input_hash)
    as_of_date = inputs.decision_engine_inputs.date
    artifact_dir = inputs.output_root / "artifacts" / "cio" / "runs" / run_id
    stage_names = ("decision_engine", "decision_journal", "portfolio_os", "performance_lab")

    if validate_only:
        statuses = tuple(StageStatus(stage=name, status="validated") for name in stage_names)
        return CIOPipelineResult(
            run_id=run_id,
            as_of_date=as_of_date,
            decision_brief=None,
            decision_records=(),
            portfolio_plan=None,
            performance_report=None,
            artifact_paths=(),
            stage_statuses=statuses,
            overall_status="validated",
            content_hash=inputs.input_hash,
        )

    stage_statuses: list[StageStatus] = []
    decision_brief = None
    decision_records: tuple[Any, ...] = ()
    portfolio_plan = None
    performance_report = None
    artifact_contents: dict[str, bytes] = {}

    try:
        with TemporaryDirectory(prefix="cio_pipeline_stage_") as temp_dir:
            stage_root = Path(temp_dir)

            # Stage 1: Decision Engine
            brief = DecisionEngine().generate(inputs.decision_engine_inputs, report_path=stage_root / "daily_cio_brief.md")
            decision_brief = brief
            artifact_contents["daily_cio_brief.md"] = render_daily_cio_brief(brief).encode("utf-8")
            stage_statuses.append(StageStatus(stage="decision_engine", status="completed"))

            # Stage 2: Decision Journal adapter
            journal = DecisionJournal(inputs.journal_root)
            records = journal.record_brief(brief)
            for outcome in inputs.realized_outcomes:
                journal.record_outcome(outcome)
            decision_records = records
            artifact_contents["decision_records.json"] = (
                json.dumps([record.to_dict() for record in records], indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            stage_statuses.append(StageStatus(stage="decision_journal", status="completed"))

            # Stage 3: Portfolio OS
            os_inputs = PortfolioOSInputs(
                date=inputs.decision_engine_inputs.date,
                decision_brief=brief,
                decision_records=records,
                realized_outcomes=inputs.realized_outcomes,
                current_portfolio=inputs.decision_engine_inputs.holdings,
                cash_balance=inputs.decision_engine_inputs.cash_balance,
                watchlist=inputs.decision_engine_inputs.watchlist,
                risk_limits=inputs.decision_engine_inputs.constraints,
                max_position_size=float(inputs.portfolio_os_settings["max_position_size"]),
                min_position_size=float(inputs.portfolio_os_settings["min_position_size"]),
                max_cash_allocation=float(inputs.portfolio_os_settings["max_cash_allocation"]),
                margin_settings=dict(inputs.portfolio_os_settings["margin_settings"]),
            )
            plan = PortfolioOS().generate_plan(os_inputs, report_path=stage_root / "portfolio_plan.md")
            portfolio_plan = plan
            artifact_contents["portfolio_plan.md"] = render_portfolio_plan(plan).encode("utf-8")
            stage_statuses.append(StageStatus(stage="portfolio_os", status="completed"))

            # Stage 4: Performance Lab
            perf_inputs = PerformanceLabInputs(
                decision_records=records,
                realized_outcomes=inputs.realized_outcomes,
                portfolio_plans=(plan,),
                daily_briefs=(brief,),
            )
            perf_report = PerformanceLab().generate(perf_inputs, report_path=stage_root / "performance_report.md")
            performance_report = perf_report
            artifact_contents["performance_report.md"] = perf_report.markdown.encode("utf-8")
            stage_statuses.append(StageStatus(stage="performance_lab", status="completed"))

        stage_statuses_tuple = tuple(stage_statuses)
        core_hashes = _stage_payload_hashes(artifact_contents)
        content_hash = _content_hash_for_mapping(core_hashes)
        created_artifacts = tuple(sorted((*artifact_contents.keys(), "pipeline_summary.json", "pipeline_manifest.json")))

        summary_payload = _build_pipeline_summary_payload(
            run_id=run_id,
            as_of_date=as_of_date,
            artifact_directory=artifact_dir,
            stage_statuses=stage_statuses_tuple,
            overall_status="success",
            blocker="",
            created_artifacts=created_artifacts,
            content_hash=content_hash,
        )
        summary_bytes = (json.dumps(summary_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        output_hashes = dict(core_hashes)
        output_hashes["pipeline_summary.json"] = _hash_bytes(summary_bytes)

        manifest_payload = {
            "run_id": run_id,
            "as_of_date": as_of_date,
            "input_hash": inputs.input_hash,
            "output_hashes": output_hashes,
            "stage_statuses": [status.__dict__ for status in stage_statuses_tuple],
            "created_artifacts": list(created_artifacts),
            "schema_version": SCHEMA_VERSION,
        }

        artifact_contents["pipeline_summary.json"] = summary_bytes
        artifact_contents["pipeline_manifest.json"] = (json.dumps(manifest_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

        if artifact_dir.exists():
            _check_existing_artifacts(artifact_dir, artifact_contents)
        else:
            _write_new_artifacts(artifact_dir, artifact_contents)

        artifact_paths = tuple(str(artifact_dir / name) for name in sorted(artifact_contents))
        return CIOPipelineResult(
            run_id=run_id,
            as_of_date=as_of_date,
            decision_brief=decision_brief,
            decision_records=decision_records,
            portfolio_plan=portfolio_plan,
            performance_report=performance_report,
            artifact_paths=artifact_paths,
            stage_statuses=stage_statuses_tuple,
            overall_status="success",
            content_hash=content_hash,
        )

    except CIOPipelineConflictError:
        raise
    except Exception as exc:
        failed_stage = stage_names[len(stage_statuses)] if len(stage_statuses) < len(stage_names) else stage_names[-1]
        blocker = str(exc)
        statuses_tuple = _stage_statuses_for_failure(stage_statuses, stage_names, failed_stage, blocker)

        completed_hashes = _stage_payload_hashes(artifact_contents)
        content_hash = _content_hash_for_mapping(completed_hashes)
        created_artifacts = tuple(sorted((*artifact_contents.keys(), "pipeline_summary.json", "pipeline_manifest.json")))

        summary_payload = _build_pipeline_summary_payload(
            run_id=run_id,
            as_of_date=as_of_date,
            artifact_directory=artifact_dir,
            stage_statuses=statuses_tuple,
            overall_status="failed",
            blocker=blocker,
            created_artifacts=created_artifacts,
            content_hash=content_hash,
        )
        summary_bytes = (json.dumps(summary_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        output_hashes = dict(completed_hashes)
        output_hashes["pipeline_summary.json"] = _hash_bytes(summary_bytes)

        manifest_payload = {
            "run_id": run_id,
            "as_of_date": as_of_date,
            "input_hash": inputs.input_hash,
            "output_hashes": output_hashes,
            "stage_statuses": [status.__dict__ for status in statuses_tuple],
            "created_artifacts": list(created_artifacts),
            "schema_version": SCHEMA_VERSION,
        }

        artifact_contents["pipeline_summary.json"] = summary_bytes
        artifact_contents["pipeline_manifest.json"] = (json.dumps(manifest_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

        if artifact_dir.exists():
            _check_existing_artifacts(artifact_dir, artifact_contents)
        else:
            _write_new_artifacts(artifact_dir, artifact_contents)

        raise CIOPipelineError(blocker) from exc
