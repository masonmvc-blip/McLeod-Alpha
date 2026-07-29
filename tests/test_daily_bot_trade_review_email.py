from pathlib import Path

from scripts import send_daily_bot_trade_review as review_email
from scripts.send_daily_bot_trade_review import (
    _compact_operational_sections,
    _email_markdown,
    _normalize_dollar_markdown,
    _reconciliation_is_sendable,
    _subject,
    _today_trades_svg,
    markdown_to_email_html,
)


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
    assert "No live sizing" in rendered


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
    assert "Day Trade SPY Five-Test Shadow Review" not in cleaned
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

    assert "## Startup Guard" in cleaned
    assert "**Decision:** **KEEP AT ONE**" in cleaned
    assert "Qualified candidates blocked today" not in cleaned
    assert "## Cooling Period" in cleaned
    assert "Ensure cooling arms reliably" in cleaned
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
    assert "## Startup Guard\n" in compacted


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


def test_summary_card_appears_before_detailed_sections():
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
    assert rendered.index(">Summary<") < rendered.index(">Today's Trades<")
    assert rendered.index(">Today's Trades<") < rendered.index(">Direction Breakdown — All Time<")
    summary_html = rendered[
        rendered.index(">Summary<"):rendered.index(">Today's Trades<")
    ]
    assert "Net P&amp;L" not in summary_html
    assert ">Trades<" not in summary_html
    assert "Win Rate" not in summary_html
    assert "Measurements Starting Or Continuing" not in summary_html
    assert "1. What We Learned" in summary_html
    assert "2. Changes We Need To Make" in summary_html
    assert "padding:0 10px 18px" in rendered
    assert "padding:0 28px 28px" in rendered
    assert "<img" not in rendered
    assert "table-layout:fixed" in rendered
    assert rendered.count('width="11.111%"') >= 9


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
    assert _subject("2026-07-29") == "You Made Today $664.25 Over 6 Trades"


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
    assert "table-layout: fixed;" in source
    assert "width: 11.111%;" in source


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
