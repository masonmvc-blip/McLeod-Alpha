from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_daily_learning_launchagent_executes_runner_with_its_bash_shebang():
    installer = (
        ROOT / "scripts" / "install_daily_trade_learning_launchagent.sh"
    ).read_text(encoding="utf-8")
    program_arguments = installer.split(
        "<key>ProgramArguments</key>", 1
    )[1].split("</array>", 1)[0]

    assert "<string>$RUNNER_PATH</string>" in program_arguments
    assert "<string>/bin/zsh</string>" not in program_arguments
