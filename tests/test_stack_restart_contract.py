from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_stack_start_uses_direct_bot_endpoint_and_preserves_operator_stop_default():
    source = (ROOT / "ops" / "stack_start.sh").read_text(encoding="utf-8")

    assert "/api/start-direct" in source
    assert '"${MCLEOD_RESUME_AFTER_PLANNED_RESTART:-0}"' in source
    assert "operator stop is active" in source


def test_nightly_restart_explicitly_resumes_planned_stop():
    source = (ROOT / "scripts" / "maintenance" / "nightly_sync_and_restart.sh").read_text(encoding="utf-8")

    assert 'MCLEOD_RESUME_AFTER_PLANNED_RESTART=1 "$ROOT/ops/stack_start.sh"' in source
