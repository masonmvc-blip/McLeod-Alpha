from engine.memory.service import Memory


def test_load_position_clears_persisted_test_symbol(tmp_path):
    position_path = tmp_path / "open_position.json"
    position_path.write_text(
        '{"direction":"CALL","entry_price":500,"stop_price":495,"target_price":510,"quantity":1,"opened":"2026-07-17T09:40:00","reason":"TEST","option_symbol":"SPY_TEST","option_entry":5,"option_delta":0.5}',
        encoding="utf-8",
    )

    memory = Memory(db_path=tmp_path / "memory.sqlite", position_path=position_path)

    assert memory.load_position(dict) is None
    assert not position_path.exists()


def test_memory_owns_runtime_compatibility_artifacts(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.db")
    pid_path = tmp_path / "runtime" / "bot.pid"
    log_path = tmp_path / "runtime" / "bot.log"

    memory.write_runtime_artifact(pid_path, 12345, "bot_pid")
    with memory.open_runtime_log(log_path, mode="w") as log_file:
        log_file.write("started\n")
    with memory.open_runtime_log(log_path, mode="a") as log_file:
        log_file.write("healthy\n")
    memory.clear_runtime_artifact(pid_path, "bot_pid")

    assert log_path.read_text(encoding="utf-8") == "started\nhealthy\n"
    assert not pid_path.exists()