from engine.architecture_health import build_architecture_health


def test_health_report_identifies_runtime_boundary_debt(tmp_path):
    (tmp_path / "execution").mkdir()
    (tmp_path / "engine" / "memory").mkdir(parents=True)
    (tmp_path / "cockpit.py").write_text(
        "import sqlite3\n"
        "def _active_stop_category(): pass\n"
        "connection = sqlite3.connect('state.db')\n"
        "connection.execute('INSERT INTO state VALUES (1)')\n",
        encoding="utf-8",
    )
    (tmp_path / "execution" / "paper_engine.py").write_text(
        "def manage_trade(): pass\n"
        "open('paper.json', 'w')\n",
        encoding="utf-8",
    )
    (tmp_path / "engine" / "memory" / "service.py").write_text(
        "import sqlite3\nsqlite3.connect('canonical.db')\n",
        encoding="utf-8",
    )

    report = build_architecture_health(tmp_path)

    assert report["brain"]["evidence"] == [
        {
            "path": "execution/paper_engine.py", "line": 1, "kind": "policy_definition", "detail": "manage_trade",
            "category": "decision_outside_brain", "why": "Trading-policy definition remains outside the canonical Brain package.",
        }
    ]
    assert {item["path"] for item in report["memory"]["evidence"]} == {
        "cockpit.py", "execution/paper_engine.py"
    }
    assert report["cockpit"]["evidence"][0]["detail"] == "_active_stop_category"
    assert report["baseline"]["known_issues"][0]["id"] == "live_engine_vwap_snapshot"


def test_scores_are_capability_based_not_ast_finding_counts(tmp_path):
    (tmp_path / "execution").mkdir()
    (tmp_path / "execution" / "paper_engine.py").write_text(
        "open('one.json', 'w')\nopen('two.json', 'w')\n",
        encoding="utf-8",
    )

    report = build_architecture_health(tmp_path)

    assert len(report["memory"]["evidence"]) == 2
    assert report["memory"]["score"] == 100
    assert report["brain"]["score"] == 100
    assert report["overall"]["score"] == 90


def test_capabilities_publish_exit_criteria_and_calculated_priorities(tmp_path):
    report = build_architecture_health(tmp_path)

    trade_management = next(item for item in report["brain"]["capabilities"] if item["id"] == "trade_management")
    entry_decisions = next(item for item in report["brain"]["capabilities"] if item["id"] == "entry_decisions")
    assert "The live execution adapter and historical replay consume Brain decisions." in trade_management["definition_of_complete"]
    assert "Brain owns entry eligibility, trade planning, startup lifecycle locks, broker-fact admission, quote-quality, and option-contract selection decisions." in entry_decisions["definition_of_complete"]
    assert report["priorities"]["priorities"][0] == {
        "id": "remove_cockpit_direct_persistence",
        "label": "Remove direct Cockpit persistence",
        "blocker": "cockpit.py",
        "targets": ["direct_persistence"],
        "impact_percent": 2,
    }
    assert report["brain"]["score"] == 100
    assert report["priorities"]["estimated_completion_after_next_milestone"] == 92


def test_version_history_is_not_a_memory_persistence_capability(tmp_path):
    report = build_architecture_health(tmp_path)

    assert "version_history" not in {item["id"] for item in report["memory"]["capabilities"]}