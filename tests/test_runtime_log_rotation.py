import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "ops" / "rotate_runtime_logs.sh"


def _run_rotation(project_dir: Path, *, timestamp: str = "20260728-210000") -> None:
    env = os.environ.copy()
    env.update(
        {
            "RUNTIME_LOG_PROJECT_DIR": str(project_dir),
            "RUNTIME_LOG_MAX_SIZE_BYTES": "10",
            "RUNTIME_TELEMETRY_MAX_SIZE_BYTES": "10",
            "RUNTIME_LOG_KEEP_FILES": "2",
            "RUNTIME_LOG_ROTATION_TIMESTAMP": timestamp,
        }
    )
    subprocess.run(["/bin/zsh", str(SCRIPT)], check=True, env=env)


def test_rotates_large_jsonl_without_recreating_projection(tmp_path):
    telemetry = tmp_path / "data" / "reports" / "latency_cycle_history.jsonl"
    telemetry.parent.mkdir(parents=True)
    telemetry.write_text("first\nsecond\n", encoding="utf-8")

    _run_rotation(tmp_path)

    rotated = tmp_path / "data" / "reports" / "latency_cycle_history.jsonl.20260728-210000"
    assert rotated.read_text(encoding="utf-8") == "first\nsecond\n"
    assert not telemetry.exists()


def test_retains_only_configured_number_of_rotations(tmp_path):
    telemetry = tmp_path / "data" / "reports" / "decision_audit_history.jsonl"
    telemetry.parent.mkdir(parents=True)
    old_one = Path(f"{telemetry}.20260726-210000")
    old_two = Path(f"{telemetry}.20260727-210000")
    old_one.write_text("old-one\n", encoding="utf-8")
    old_two.write_text("old-two\n", encoding="utf-8")
    os.utime(old_one, (1, 1))
    os.utime(old_two, (2, 2))
    telemetry.write_text("new-projection\n", encoding="utf-8")

    _run_rotation(tmp_path)

    rotations = sorted(telemetry.parent.glob(f"{telemetry.name}.*"))
    assert len(rotations) == 2
    assert old_one not in rotations
    assert old_two in rotations
    assert Path(f"{telemetry}.20260728-210000") in rotations


def test_does_not_rotate_small_projection(tmp_path):
    telemetry = tmp_path / "data" / "reports" / "runtime_events.jsonl"
    telemetry.parent.mkdir(parents=True)
    telemetry.write_text("small\n", encoding="utf-8")

    _run_rotation(tmp_path)

    assert telemetry.read_text(encoding="utf-8") == "small\n"
    assert list(telemetry.parent.glob(f"{telemetry.name}.*")) == []
