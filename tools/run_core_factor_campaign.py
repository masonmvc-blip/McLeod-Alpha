from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from engine.factors.library import core_factors
from engine.research_lab.experiment import canonical_bytes, content_hash


CAMPAIGN_ID = "core_factor_v1"
SNAPSHOT_ROOT = Path("artifacts/replay/example_dataset/snapshots")


def _read_snapshots(root: Path) -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.json"))) if root.is_dir() else ()


def build_campaign(*, repository_root: Path, output_root: Path | None = None) -> dict[str, Any]:
    destination = output_root or repository_root / "artifacts" / "factor_campaigns" / CAMPAIGN_ID
    snapshots = _read_snapshots(repository_root / SNAPSHOT_ROOT)
    factors = core_factors()
    readiness = []
    gaps = []
    for factor in factors:
        fields = list(factor.metadata.dependencies)
        available = sorted({key for snapshot in snapshots for key in (snapshot.get("company_fundamentals") or {})})
        missing = sorted(set(fields) - set(available))
        reasons = ["no canonical historical universe membership", "no verified availability timestamp coverage", "survivorship bias cannot be controlled"]
        if missing: reasons.append("required factor fields unavailable")
        readiness.append({"factor_id": factor.metadata.factor_id, "version": factor.metadata.version, "required_fields": fields, "available_fields": available, "missing_fields": missing, "available_date_range": None, "symbol_count": 0, "observation_count": 0, "point_in_time_timestamp_coverage": False, "survivorship_bias_risk": "UNCONTROLLED", "lookahead_risk_status": "NOT_ESTABLISHED", "experiment_readiness": "NOT_READY", "reasons": sorted(reasons)})
        gaps.append({"factor_id": factor.metadata.factor_id, "missing_fields": missing, "blockers": sorted(reasons)})
    results = [{"factor_id": item["factor_id"], "version": item["version"], "experiment_id": None, "certification_id": None, "data_period": None, "symbols_tested": [], "observations_accepted": 0, "observations_rejected": 0, "rejection_reasons": item["reasons"], "train_metrics": None, "test_metrics": None, "effect_size": None, "confidence_interval": None, "stability": None, "turnover": None, "drawdown_impact": None, "certification_decision": None, "status": "NOT_READY"} for item in readiness]
    rejections = [{"factor_id": item["factor_id"], "rejection_reason": reason} for item in readiness for reason in item["reasons"]]
    payloads = {"data_readiness.json": readiness, "data_gaps.json": gaps, "factor_results.json": results, "observation_rejections.json": rejections}
    summary = {"campaign_id": CAMPAIGN_ID, "campaign_hash": content_hash({"campaign_id": CAMPAIGN_ID, "readiness": readiness}), "ready_factors": [], "partial_factors": [], "not_ready_factors": [item["factor_id"] for item in readiness], "experiments_completed": 0, "certifications_completed": 0, "canonical_snapshot_count": 0, "result_hashes": {name: content_hash(value) for name, value in sorted(payloads.items())}}
    payloads["campaign_summary.json"] = summary
    lines = ["# Core Factor v1 Campaign", "", "## Result", "", "No experiments were run. All factors are NOT_READY because the repository has no canonical historical point-in-time universe with verified availability timestamps and survivorship controls.", "", "## Factors"] + [f"- {item['factor_id']}: NOT_READY" for item in readiness]
    files = {name: canonical_bytes(value) for name, value in payloads.items()}
    files["data_readiness.md"] = ("# Core Factor Data Readiness\n\n" + "\n".join(f"- {item['factor_id']}: NOT_READY ({'; '.join(item['reasons'])})" for item in readiness) + "\n").encode("utf-8")
    files["campaign_summary.md"] = ("\n".join(lines) + "\n").encode("utf-8")
    manifest = {"campaign_id": CAMPAIGN_ID, "artifact_hashes": {name: sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files["campaign_manifest.json"] = canonical_bytes(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        path = destination / name
        if path.exists() and path.read_bytes() != data: raise FileExistsError(f"campaign artifact conflict: {path}")
        path.write_bytes(data)
    return {"output_path": destination, "summary": summary, "readiness": readiness, "manifest": manifest}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(build_campaign(repository_root=root)["output_path"])