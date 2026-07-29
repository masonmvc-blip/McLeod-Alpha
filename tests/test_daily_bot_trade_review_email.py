from pathlib import Path

from scripts import send_daily_bot_trade_review as review_email
from scripts.send_daily_bot_trade_review import markdown_to_email_html


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


def test_review_email_script_uses_repo_data_paths():
    source = Path("scripts/send_daily_bot_trade_review.py").read_text(encoding="utf-8")
    assert 'ROOT / "data" / "learning"' in source
    assert "last_artifact_sha256" in source


def test_smtp_uses_working_email_credentials(monkeypatch):
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
        attachments=[],
    )

    assert captured["host"] == "smtp.gmail.com"
    assert captured["username"] == "sender@gmail.com"
    assert captured["password"] == "abcdefghijklmnop"
    assert captured["recipient"] == "recipient@example.com"
