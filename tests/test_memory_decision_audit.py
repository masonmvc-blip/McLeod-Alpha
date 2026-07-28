import json

from engine.memory.service import Memory


def test_load_latest_decision_audit_event_skips_unscored_records(tmp_path):
    audit_path = tmp_path / "decision_audit_history.jsonl"
    audit_path.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {"event_type": "entry_evaluation", "candle_time": "2026-07-28T18:24:00+00:00", "call_score": 1, "put_score": 3},
                {"event_type": "entry_evaluation", "candle_time": "2026-07-28T18:25:00+00:00", "call_score": None, "put_score": None},
                {"event_type": "heartbeat"},
            )
        ) + "\n",
        encoding="utf-8",
    )

    event = Memory(db_path=tmp_path / "memory.db").load_latest_decision_audit_event(audit_path)

    assert event["candle_time"] == "2026-07-28T18:24:00+00:00"
    assert event["call_score"] == 1
    assert event["put_score"] == 3