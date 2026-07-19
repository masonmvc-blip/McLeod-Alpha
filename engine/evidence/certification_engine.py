from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import shutil
from tempfile import TemporaryDirectory
from typing import Any

from .certification_policy import validate_policy
from .certification_report import decision_markdown
from .certification_schema import Certification, CertificationPolicy, canonical_bytes, content_hash
from .economic_significance import economic_significance
from .regime_validation import regime_stability_score
from .reproducibility_check import load_verified_artifacts


def _number(mapping: Any, *names: str) -> float:
    if isinstance(mapping, (int, float)):
        return float(mapping)
    if not isinstance(mapping, dict):
        return 0.0
    for name in names:
        if name in mapping:
            return float(mapping[name])
    return 0.0


def certify_experiment(experiment_path: Path | str, policy: CertificationPolicy, output_root: Path | str) -> dict[str, Any]:
    validate_policy(policy)
    evidence = load_verified_artifacts(experiment_path)
    metrics, statistics = evidence["metrics"], evidence["statistics"]
    train_test = statistics.get("train_test", {})
    bootstrap = statistics.get("bootstrap_ci", {})
    t_test = statistics.get("t_test", {})
    reasons: list[str] = []
    failures: list[str] = []
    def check(condition: bool, label: str) -> None:
        (reasons if condition else failures).append(label)
    train = _number(train_test, "train", "train_performance")
    test = _number(train_test, "test", "test_performance")
    confidence = 1.0 - _number(t_test, "p_value")
    lower_bound = _number(bootstrap, "lower", "lower_bound")
    effect = _number(statistics.get("effect_size", {}), "effect_size", "value")
    check(train >= policy.minimum_train_performance, "train performance")
    check(test >= policy.minimum_test_performance, "test performance")
    check(test >= 0.0 and train >= 0.0, "train/test consistency")
    check(confidence >= policy.minimum_confidence_level and lower_bound >= 0.0, "statistical and bootstrap confidence")
    check(effect >= policy.minimum_effect_size, "effect size")
    check(regime_stability_score(statistics) >= policy.minimum_stability_score, "regime stability")
    check(economic_significance(metrics) >= policy.minimum_economic_significance, "economic significance")
    check(abs(_number(metrics, "Turnover")) <= policy.maximum_turnover_increase, "turnover impact")
    check(abs(_number(metrics, "Max_Drawdown")) <= policy.maximum_drawdown_increase, "drawdown impact")
    check(_number(metrics, "Exposure") >= 0.0, "exposure change")
    check(1.0 >= policy.minimum_reproducibility_score, "reproducibility")
    decision = "CERTIFIED" if not failures else ("NEEDS_MORE_EVIDENCE" if len(failures) <= 2 else "REJECTED")
    rationale = tuple(sorted(([f"passed: {reason}" for reason in reasons] + [f"failed: {reason}" for reason in failures])))
    timestamp = policy.created_at
    identity = {"experiment_id": evidence["experiment"]["experiment_id"], "policy_hash": policy.policy_hash, "artifact_hash": evidence["artifact_hash"]}
    certification = Certification(certification_id=content_hash(identity), experiment_id=identity["experiment_id"], policy_id=policy.policy_id, policy_version=policy.version, decision=decision, timestamp=timestamp, artifact_hash=identity["artifact_hash"], policy_hash=policy.policy_hash, rationale=rationale)
    files = {"certification.json": canonical_bytes(certification.to_dict()), "decision.md": decision_markdown(certification), "rationale.json": canonical_bytes({"rationale": rationale})}
    manifest = {"certification_id": certification.certification_id, "policy_hash": policy.policy_hash, "artifact_hashes": {name: sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files["manifest.json"] = canonical_bytes(manifest)
    target = Path(output_root) / certification.certification_id
    if target.exists():
        existing = {entry.name: entry.read_bytes() for entry in target.iterdir() if entry.is_file()}
        if existing != files:
            raise FileExistsError(f"certification artifact conflict: {target}")
    else:
        with TemporaryDirectory(prefix="evidence_") as temporary:
            stage = Path(temporary) / certification.certification_id
            stage.mkdir()
            for name, data in files.items():
                (stage / name).write_bytes(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.parent / f".{target.name}.staging"
            if pending.exists(): shutil.rmtree(pending)
            shutil.copytree(stage, pending)
            os.replace(pending, target)
    return {"certification": certification, "output_path": target, "manifest": manifest}