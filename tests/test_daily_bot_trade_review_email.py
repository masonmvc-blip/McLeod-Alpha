from pathlib import Path

from scripts import send_daily_bot_trade_review as review_email
from scripts.send_daily_bot_trade_review import (
    _bot_cockpit_failures_summary,
    _build_email_summary,
    _compact_missed_opportunity_sections,
    _compact_operational_sections,
    _day_trade_spy_all_time_summary,
    _email_markdown,
    _execution_reliability_summary,
    _normalize_dollar_markdown,
    _reconciliation_is_sendable,
    _subject,
    _today_trades_email_html,
    _today_trades_svg,
    markdown_to_email_html,
)


def test_summary_uses_only_all_time_evidence_and_20_50_gate(monkeypatch):
    monkeypatch.setattr(
        review_email,
        "_all_time_study_trades",
        lambda _date: [
            {"pnl_dollars": 100.0},
            {"pnl_dollars": -25.0},
        ],
    )
    monkeypatch.setattr(
        review_email,
        "_load_json",
        lambda path: (
            {"rolling": {"valid_sample_size": 11}}
            if "day_trade_spy_shadow" in str(path)
            else {"telemetry_quality": {"rolling_complete": 1}}
        ),
    )

    summary = _build_email_summary("2026-07-29")

    text = str(summary)
    assert "2 canonical broker-backed trades" in text
    assert "11/50 valid all-time trades" in text
    assert "20 comparable trades" in text
    assert "prefer 50" in text
    assert "today" not in text.lower()


def test_day_trade_spy_review_exposes_all_five_catalog_rules(monkeypatch):
    groups = {
        "ADMIT": {"trades": 2, "wins": 1, "pnl_dollars": 10.0},
    }
    monkeypatch.setattr(
        review_email,
        "_load_json",
        lambda _path: {
            "rolling": {
                "valid_sample_size": 11,
                "known_first_passage": 10,
                "session_phase_counts": {"OPENING": 3, "MIDDAY": 4},
                "test_summary": {
                    key: groups for key in (
                        "accepted_break",
                        "structural_room_execution",
                        "opening_vs_later_entry",
                        "congestion_reentry",
                        "premise_reset_no_repair",
                    )
                },
            },
        },
    )

    review = _day_trade_spy_all_time_summary("2026-07-29")

    assert "## Day Trade SPY Review — All Time" in review
    for title in (
        "Accepted Break",
        "Structural Room & Execution",
        "Opening vs. Later Entry",
        "Congestion & Re-entry",
        "Premise Reset / No Repair",
    ):
        assert title in review
    assert "11/50" in review
    assert "COLLECT MORE DATA" in review
    assert "These are the five video-derived rules" not in review


def test_bot_cockpit_failures_combines_structured_daily_sources(monkeypatch):
    def fake_load(path):
        name = str(path)
        if "stop_execution_review" in name:
            return {"summary": {
                "ratchet_failures": 2,
                "protective_submission_failures": 1,
                "replacement_rejections": 1,
                "protective_stop_missing_decisions": 3,
                "entry_adverse_slippage_dollars_per_contract": 0.05,
                "exit_execution_shortfall_dollars_per_contract": 0.10,
            }}
        if "cooling_period_review" in name:
            return {"summary": {
                "harmful_uncooled_reentries": 1,
                "harmful_uncooled_reentry_pnl": -50.0,
            }}
        return {"today_trades": [{"source": "broker_duplicate_audit"}]}

    monkeypatch.setattr(review_email, "_load_json", fake_load)
    monkeypatch.setattr(
        review_email,
        "_runtime_failure_counts",
        lambda _date: {"Manual Exit Failure": 1},
    )

    review = _bot_cockpit_failures_summary("2026-07-29")

    assert "## Bot & Cockpit Failures — Today" in review
    assert "2 ratchet failures" in review
    assert "cooling failed to arm" in review.lower()
    assert "duplicate canonical trade" in review
    assert "Manual Exit Failure" in review
    assert "**Response:**" not in review


def test_execution_reliability_box_uses_all_available_review_history(monkeypatch):
    monkeypatch.setattr(
        review_email,
        "_daily_report_history",
        lambda _prefix, _date: [
            {
                "summary": {
                    "ratchet_failures": 2,
                    "protective_submission_failures": 1,
                    "replacement_rejections": 0,
                    "protective_stop_missing_decisions": 1,
                },
                "trades": [
                    {
                        "status": "HEALTHY",
                        "execution_quality": {
                            "entry_adverse_slippage_dollars": 0.0,
                            "exit_execution_shortfall_dollars": 0.10,
                            "management_cycle_median_seconds": 1.0,
                            "estimated_round_trip_execution_drag_dollars": 50.0,
                        },
                    },
                    {
                        "status": "REVIEW_REQUIRED",
                        "execution_quality": {
                            "entry_adverse_slippage_dollars": 0.20,
                            "exit_execution_shortfall_dollars": 0.30,
                            "management_cycle_median_seconds": 1.5,
                            "estimated_round_trip_execution_drag_dollars": 100.0,
                        },
                    },
                ],
            },
        ],
    )

    review = _execution_reliability_summary("2026-07-29")

    assert "## Execution & Reliability — All Time" in review
    assert "**50.0%**" in review
    assert "1/2 broker-backed trades" in review
    assert "$150.00" in review
    assert "1.25s median" in review
    assert "OPEN — REPAIR REQUIRED" in review


def test_markdown_to_email_html_renders_review_sections():
    rendered = markdown_to_email_html(
        """# McLeod Alpha Bot Trade Review — 2026-07-28

## Reconciliation

- Broker result: **5 trades, +$95.63**.

### Highest-Value Improvement

1. Verify the exact stop.
""",
        "2026-07-28",
    )

    assert "Daily Bot Trade Review" in rendered
    assert "<h2>Reconciliation</h2>" in rendered
    assert "<strong>5 trades, +$95.63</strong>" in rendered
    assert "Verify the exact stop" in rendered
    assert "Evidence is diagnostic" not in rendered


def test_markdown_to_email_html_renders_tables_as_styled_html():
    rendered = markdown_to_email_html(
        "| Phase | Trades | P&L |\n"
        "| --- | ---: | ---: |\n"
        "| INITIATION | 2 | $10.00 |\n",
        "2026-07-28",
    )
    assert "<table" in rendered
    assert "<th" in rendered
    assert "INITIATION" in rendered
    assert "| ---" not in rendered


def test_email_body_removes_generator_metadata_and_core_performance():
    cleaned = _email_markdown(
        "# Daily Trade Learning Report\n\n"
        "Date: 2026-07-29\n"
        "Generated: 2026-07-29T16:50:09\n\n"
        "## Core Performance\n\n"
        "| Slice | Trades |\n"
        "| --- | ---: |\n"
        "| Overall | 6 |\n\n"
        "## Exit Reason Breakdown\n\n"
        "| Exit | P&L |\n"
    )

    assert "Daily Trade Learning Report" not in cleaned
    assert "Date:" not in cleaned
    assert "Generated:" not in cleaned
    assert "Core Performance" not in cleaned
    assert "| Overall | 6 |" not in cleaned
    assert "## Exit Reason Breakdown" not in cleaned


def test_email_view_hides_requested_sections_without_altering_source_artifact():
    source = (
        "## Biggest Losses (Top 5)\n\nPrivate learning detail\n\n"
        "## Actionable Lessons\n\n- Keep measuring exits\n\n"
        "## Scale Decision (Next Session)\n\n### Scale Gate Checks\n\n- Hidden\n\n"
        "## Model Learning Jobs\n\n- Still runs locally\n\n"
        "## Trend Lifecycle V2 Shadow Review\n\n### Evidence Gate\n\n- Hidden\n\n"
        "## Entry Quality Shadow Studies\n\n### Today's Recorded Metrics\n\n- Hidden\n\n"
        "## Day Trade SPY Five-Test Shadow Review\n\n- Hidden research review\n\n"
        "## Volume — Daily Shadow Test\n\nHidden volume summary\n\n"
        "### Indicator Weight Shadow Comparisons\n\n- Hidden weights\n\n"
        "### Historical Context\n\n- Hidden history\n\n"
        "### Fresh Forward Sample\n\n- Hidden sample\n\n"
        "### Evidence Gate: **COLLECT_MORE_DATA**\n\n- Hidden gate detail\n\n"
        "### Alternative Checklist Policies\n\nHidden policy detail\n\n"
        "### Broker-Backed Executed Trades\n\nHidden broker trades\n\n"
        "## Option Selection — Spread-Aware Shadow Ranking\n\n"
        "### Today's Contract Comparisons\n\nHidden contracts\n\n"
        "## Missed Opportunities — Shadow Review\n\n"
        "### Daily Scorecard\n\nVisible scorecard\n\n"
        "### Canonical Missed Opportunities\n\nVisible canonical misses\n\n"
        "### Losses Correctly Avoided\n\n- Hidden avoided losses\n\n"
        "### Recurring Rejection Patterns\n\n- Hidden rejection patterns\n\n"
        "### Blocker Usefulness\n\nVisible blocker usefulness\n\n"
        "### Locked Evidence Gates\n\n- Hidden locked gates\n\n"
        "## Exit Reason Breakdown\n\nVisible\n"
    )
    cleaned = _email_markdown(source)

    assert "Biggest Losses" not in cleaned
    assert "Actionable Lessons" not in cleaned
    assert "Scale Gate Checks" not in cleaned
    assert "Model Learning Jobs" not in cleaned
    assert "Trend Lifecycle V2" not in cleaned
    assert "Entry Quality Shadow Studies" not in cleaned
    assert "Day Trade SPY Five-Test Shadow Review" in cleaned
    assert "Indicator Weight Shadow Comparisons" not in cleaned
    assert "Historical Context" not in cleaned
    assert "Fresh Forward Sample" not in cleaned
    assert "Evidence Gate" not in cleaned
    assert "Hidden gate detail" not in cleaned
    assert "Missed Opportunities — Shadow Review" not in cleaned
    assert "Daily Scorecard" in cleaned
    assert "Visible scorecard" in cleaned
    assert "Canonical Missed Opportunities" in cleaned
    assert "Visible canonical misses" in cleaned
    assert "Losses Correctly Avoided" not in cleaned
    assert "Recurring Rejection Patterns" not in cleaned
    assert "Blocker Usefulness" in cleaned
    assert "Visible blocker usefulness" in cleaned
    assert "Locked Evidence Gates" not in cleaned
    assert "Volume — Daily Shadow Test" not in cleaned
    assert "Hidden volume summary" not in cleaned
    assert "Alternative Checklist Policies" not in cleaned
    assert "Hidden policy detail" not in cleaned
    assert "Broker-Backed Executed Trades" not in cleaned
    assert "Option Selection — Spread-Aware Shadow Ranking" not in cleaned
    assert "Today's Contract Comparisons" not in cleaned
    assert "## Exit Reason Breakdown" not in cleaned
    assert "Private learning detail" in source
    assert "Still runs locally" in source


def test_email_compacts_controls_and_hides_session_market_trend():
    source = """## Startup Guard — Daily Assessment

- Current setting: block the first **1** otherwise-qualified entry after startup.
- Today’s recommendation: **KEEP_AT_ONE**.
- Rationale: The sample remains too small.
- Qualified candidates blocked today: **5**.
- Prompt same-contract opportunities preserved: **2**.
- Executable outcome coverage: **80.0%**.
- Change gate: at least **20** decisive setups.

## Cooling Period — Daily Assessment

- Current behavior: skip the next **one signal** after every confirmed exit.
- Today’s recommendation: **KEEP_AT_ONE**.
- Rationale: One harmful re-entry occurred without cooling.
- Cooling blocks observed today: **3**.
- Profitable opportunities blocked: **2**; losses correctly avoided: **1**.
- Harmful uncooled re-entries: **1** for **-$134.41**.
- Executable blocked-signal coverage: **100.0%**.
- Change gate: at least **20** decisive blocks.

## Session Market Trend — Entry Shadow Test

- Hidden research detail.

## Protective Stop and Ratchet Reliability

- Trades observed: **6**; broker stop submissions: **30**.
- Ratchet failures: **193**; rejected replacements: **8**; identity recoveries: **0**.

| Trade | Status |
| --- | --- |
| one | REVIEW_REQUIRED |
"""
    cleaned = _email_markdown(source)

    assert "## Startup Guard — All Time" in cleaned
    assert "**Decision:** Keep at one" in cleaned
    assert "Qualified candidates blocked today" not in cleaned
    assert "## Cooling Period — All Time" in cleaned
    assert "ensure it arms after every confirmed exit" in cleaned
    assert "losses correctly avoided" not in cleaned
    assert "Session Market Trend" not in cleaned
    assert "Hidden research detail" not in cleaned
    assert "## Protective Stops" in cleaned
    assert "**Status:** Repair required" in cleaned
    assert "| Trade | Status |" not in cleaned
    assert "Ratchet failures" not in cleaned
    assert "193" in cleaned


def test_compact_operational_sections_does_not_mutate_full_report_text():
    source = "## Startup Guard — Daily Assessment\n\n- Current setting: **1**.\n"
    compacted = _compact_operational_sections(source)

    assert "## Startup Guard — Daily Assessment" in source
    assert "## Startup Guard — All Time\n" in compacted


def test_missed_opportunities_uses_separate_all_time_h2_headers(
    monkeypatch,
):
    monkeypatch.setattr(
        review_email,
        "_load_json",
        lambda _path: {
            "summary": {
                "canonical_missed_opportunities": 1,
                "unseen_market_moves": 1,
                "near_miss_opportunities": 0,
                "option_evidence_coverage": 0.75,
            },
            "missed_opportunities": [{"classification": "MISSED_PROFITABLE_OPPORTUNITY"}],
            "rolling_canonical_episodes": 2,
            "pattern_summary": [{
                "direction": "PUT",
                "phase": "INITIATION",
                "rejection_reason": "Regime mismatch",
                "missed_profitable": 1,
                "canonical_episodes": 2,
            }],
            "blocker_summary": [{
                "blocker_code": "REGIME_MATCH",
                "canonical_episodes": 2,
                "sole_blocker_episodes": 1,
                "missed_profitable": 1,
                "losses_avoided": 1,
            }],
        },
    )
    source = """## Missed Opportunities — Shadow Review

### Daily Scorecard

- Daily facts.

### Canonical Missed Opportunities

- Old detail.

### Blocker Usefulness

- Old blocker detail.
"""

    compacted = _compact_missed_opportunity_sections(source, "2026-07-29")

    assert "## Daily Scorecard" in compacted
    assert "## Missed Opportunities — All Time" in compacted
    assert "## Block Usefulness — All Time" in compacted
    assert compacted.index("## Missed Opportunities — All Time") < compacted.index(
        "## Block Usefulness — All Time"
    )
    assert "### Canonical Missed Opportunities" not in compacted
    assert "### Blocker Usefulness" not in compacted


def test_email_currency_normalization_formats_monetary_tables_and_signals():
    normalized = _normalize_dollar_markdown(
        "| Exit Reason | Trades | PnL | Win Rate |\n"
        "| --- | ---: | ---: | ---: |\n"
        "| STOP | 1 | -198.39 | 0.0% |\n\n"
        "- Signal: stop_pnl=-198.39 and PUT outperformed CALL by 207.73\n"
    )

    assert "| STOP | 1 | -$198.39 | 0.0% |" in normalized
    assert "stop_pnl=-$198.39" in normalized
    assert "outperformed CALL by $207.73" in normalized


def test_today_trades_appears_before_summary_without_tracker():
    rendered = markdown_to_email_html(
        "## Direction Breakdown — All Time\n\nDetails",
        "2026-07-29",
        summary={
            "lessons": [{
                "title": "Protect exits",
                "signal": "stop_pnl=-198.39",
                "action": "Keep measuring ratchet reliability.",
            }],
            "changes": ["Keep measuring ratchet reliability."],
        },
        trades=[{
            "time": "2:42 – 2:46",
            "option": "740 CALL",
            "contracts": "8",
            "entry": "$7.71",
            "exit": "$8.18",
            "checklist": "7 / 5",
            "phase": "Early Continuation",
            "pnl": "$228.26 · +6.1%",
            "exit_reason": "4% Stop",
            "positive": True,
        }],
    )

    assert rendered.index(">Summary<") < rendered.index(">Direction Breakdown — All Time<")
    assert rendered.index(">Today's Trades<") < rendered.index(">Summary<")
    assert "SPY Trade Tracker" not in rendered
    summary_html = rendered[
        rendered.index(">Summary<"):rendered.index(">Direction Breakdown — All Time<")
    ]
    assert "Net P&amp;L" not in summary_html
    assert ">Trades<" not in summary_html
    assert "Win Rate" not in summary_html
    assert "Measurements Starting Or Continuing" not in summary_html
    assert "What We Learned" in summary_html
    assert "Changes We Need To Make" in summary_html
    assert "1. What We Learned" not in summary_html
    assert "2. Changes We Need To Make" not in summary_html
    assert "padding:0 4px 4px" in rendered
    assert "padding:0 12px 7px" in rendered
    assert "<img" not in rendered
    assert "table-layout:auto" in rendered
    assert 'width="11.111%"' not in rendered
    assert "padding:3px 3px" in rendered
    assert "display:none;max-height:0" not in rendered
    assert "Evidence is diagnostic" not in rendered


def test_today_trades_snapshot_omits_diagnostic_columns():
    svg = _today_trades_svg(
        "2026-07-29",
        [{
            "time": "2:42 – 2:46",
            "option": "740 CALL",
            "contracts": "5",
            "entry": "$7.71",
            "exit": "$8.18",
            "checklist": "7 / 5",
            "phase": "Early Continuation",
            "cq": "4.11",
            "mas": "3.75",
            "abs": "3.33",
            "conf": "4.17",
            "pnl": "$228.26 · +6.1%",
            "exit_reason": "4% Stop",
            "positive": True,
        }],
    )

    assert "Today's Trades" in svg
    assert "740 CALL" in svg
    assert "$228.26 · +6.1%" in svg
    assert "4% Stop" in svg
    assert ">CQ<" not in svg
    assert ">MAS<" not in svg
    assert ">ABS<" not in svg
    assert ">CONF<" not in svg


def test_today_trades_option_and_pnl_are_not_bold():
    rendered = _today_trades_email_html([{
        "time": "2:42 – 2:46",
        "option": "740 CALL",
        "contracts": "8",
        "entry": "$7.71",
        "exit": "$8.18",
        "checklist": "7 / 5",
        "phase": "Early Continuation",
        "pnl": "$228.26 · +6.1%",
        "exit_reason": "4% Stop",
        "positive": True,
    }])

    assert rendered.count("font-weight:500;white-space:nowrap") == 9
    assert "font-weight:700;white-space:nowrap" not in rendered


def test_subject_uses_reconciled_broker_result(monkeypatch):
    monkeypatch.setattr(
        review_email,
        "_reconciliation",
        lambda _: {
            "complete": True,
            "count_reconciled": True,
            "pnl_reconciled": True,
            "broker_trades_today": 6,
            "canonical_completed_trades": 6,
            "broker_pnl_dollars": 664.25,
            "canonical_pnl_dollars": 664.25,
            "pending_outbox_entries": 0,
        },
    )
    assert _subject("2026-07-29") == "Made $664.25 Today On 6 Trades"


def test_reconciliation_gate_requires_exact_parity_and_empty_outbox():
    complete = {
        "complete": True,
        "count_reconciled": True,
        "pnl_reconciled": True,
        "broker_trades_today": 6,
        "canonical_completed_trades": 6,
        "broker_pnl_dollars": 664.25,
        "canonical_pnl_dollars": 664.25,
        "pending_outbox_entries": 0,
    }
    assert _reconciliation_is_sendable(complete) is True
    assert _reconciliation_is_sendable({
        **complete,
        "pending_outbox_entries": 1,
    }) is False
    assert _reconciliation_is_sendable({
        **complete,
        "canonical_completed_trades": 7,
    }) is False


def test_review_email_script_uses_repo_data_paths():
    source = Path("scripts/send_daily_bot_trade_review.py").read_text(encoding="utf-8")
    assert 'ROOT / "data" / "learning"' in source
    assert "last_artifact_sha256" in source
    assert "entry_quality_shadow" in source
    assert "volume_shadow" in source
    assert "## Volume — Daily Shadow Test" in source
    assert "option_selection_shadow" in source
    assert "## Option Selection — Spread-Aware Shadow Ranking" in source
    assert "missed_opportunities_shadow" in source
    assert "startup_guard_review" in source
    assert "cooling_period_review" in source
    assert "market_trend_shadow" in source
    assert "stop_execution_review" in source
    assert "day_trade_spy_shadow" in source
    assert "day_trade_spy_shadow" in Path("run_daily_trade_learning.py").read_text(encoding="utf-8")
    assert "volume_shadow" in Path("run_daily_trade_learning.py").read_text(encoding="utf-8")
    assert "option_selection_shadow" in Path("run_daily_trade_learning.py").read_text(encoding="utf-8")
    assert "missed_opportunities_shadow" in Path("run_daily_trade_learning.py").read_text(encoding="utf-8")
    assert "market_trend_shadow" in Path("run_daily_trade_learning.py").read_text(encoding="utf-8")
    assert "stop_execution_review" in Path("run_daily_trade_learning.py").read_text(encoding="utf-8")


def test_cockpit_hides_entry_diagnostics_but_keeps_their_telemetry():
    source = Path("cockpit.py").read_text(encoding="utf-8")

    assert "<th>CQ</th>" not in source
    assert "<th>MAS</th>" not in source
    assert "<th>ABS</th>" not in source
    assert "<th>Conf</th>" not in source
    assert "trade['continuation_quality_score']" in source
    assert "trade['momentum_acceleration_score']" in source
    assert "trade['absorption_score']" in source
    assert "trade['confidence_score']" in source
    assert ".trades-table {" in source
    assert "table-layout: auto;" in source
    assert "width: 11.111%;" not in source
    assert "padding: 6px 10px;" in source


def test_smtp_uses_working_email_credentials(monkeypatch, tmp_path):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            captured.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            captured["starttls"] = True

        def login(self, username, password):
            captured.update(username=username, password=password)

        def send_message(self, message):
            captured["recipient"] = message["To"]
            captured["sender"] = message["From"]
            captured["attachments"] = list(message.iter_attachments())
            captured["inline_images"] = [
                part for part in message.walk()
                if part.get_content_type().startswith("image/")
                and part.get_content_disposition() == "inline"
            ]

    for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EMAIL_ADDRESS", "sender@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(review_email.smtplib, "SMTP", FakeSMTP)
    review_email._send_smtp(
        recipient="recipient@example.com",
        subject="Test",
        text_body="Text",
        html_body="<p>HTML</p>",
    )

    assert captured["host"] == "smtp.gmail.com"
    assert captured["username"] == "sender@gmail.com"
    assert captured["password"] == "abcdefghijklmnop"
    assert captured["recipient"] == "recipient@example.com"
    assert captured["sender"] == "McLeod Alpha Daily Review <sender@gmail.com>"
    assert captured["attachments"] == []
    assert captured["inline_images"] == []
