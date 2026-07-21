from engine.memory.service import Memory


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