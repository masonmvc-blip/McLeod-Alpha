from pathlib import Path

from scripts import send_daily_bot_trade_review as review_email
from scripts.send_daily_bot_trade_review import (
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
    assert "## Exit Reason Breakdown" in cleaned


def test_email_view_hides_requested_sections_without_altering_source_artifact():
    source = (
        "## Biggest Losses (Top 5)\n\nPrivate learning detail\n\n"
        "## Actionable Lessons\n\n- Keep measuring exits\n\n"
        "## Scale Decision (Next Session)\n\n### Scale Gate Checks\n\n- Hidden\n\n"
        "## Model Learning Jobs\n\n- Still runs locally\n\n"
        "## Trend Lifecycle V2 Shadow Review\n\n### Evidence Gate\n\n- Hidden\n\n"
        "## Entry Quality Shadow Studies\n\n### Today's Recorded Metrics\n\n- Hidden\n\n"
        "## Day Trade SPY Five-Test Shadow Review\n\n- Hidden research review\n\n"
        "## Volume — Daily Shadow Test\n\nVisible volume summary\n\n"
        "### Indicator Weight Shadow Comparisons\n\n- Hidden weights\n\n"
        "### Historical Context\n\n- Hidden history\n\n"
        "### Fresh Forward Sample\n\n- Hidden sample\n\n"
        "### Evidence Gate: **COLLECT_MORE_DATA**\n\n- Hidden gate detail\n\n"
        "### Alternative Checklist Policies\n\nVisible policy detail\n\n"
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
    assert "Visible volume summary" in cleaned
    assert "Visible policy detail" in cleaned
    assert "## Exit Reason Breakdown" in cleaned
    assert "Private learning detail" in source
    assert "Still runs locally" in source


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
        "## Exit Reason Breakdown\n\nDetails",
        "2026-07-29",
        summary={
            "pnl": 664.25,
            "trades": 6,
            "wins": 4,
            "losses": 2,
            "win_rate": 0.6667,
            "lessons": [{
                "title": "Protect exits",
                "signal": "stop_pnl=-198.39",
                "action": "Keep measuring ratchet reliability.",
            }],
            "next_session": "Hold live settings unchanged.",
            "measurements": ["Track executable spread cost."],
        },
        trades_image_src="cid:mcleod-alpha-todays-trades",
    )

    assert rendered.index(">Summary<") < rendered.index(">Exit Reason Breakdown<")
    assert rendered.index(">Summary<") < rendered.index("alt=\"Today's Trades\"")
    assert rendered.index("alt=\"Today's Trades\"") < rendered.index(">Exit Reason Breakdown<")
    assert "$664.25" in rendered
    assert "padding:8px 10px 18px" in rendered


def test_today_trades_snapshot_contains_cockpit_columns():
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
    image_path = tmp_path / "today.png"
    image_path.write_bytes(b"png")

    review_email._send_smtp(
        recipient="recipient@example.com",
        subject="Test",
        text_body="Text",
        html_body="<p>HTML</p>",
        inline_image_path=image_path,
    )

    assert captured["host"] == "smtp.gmail.com"
    assert captured["username"] == "sender@gmail.com"
    assert captured["password"] == "abcdefghijklmnop"
    assert captured["recipient"] == "recipient@example.com"
    assert captured["sender"] == "McLeod Alpha Daily Review <sender@gmail.com>"
    assert captured["attachments"] == []
    assert len(captured["inline_images"]) == 1
    assert captured["inline_images"][0]["Content-ID"] == "<mcleod-alpha-todays-trades>"
