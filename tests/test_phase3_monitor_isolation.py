from __future__ import annotations

import ast
import importlib
import threading
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_import_has_no_runtime_initialization(monkeypatch) -> None:
    import execution.equity_stream
    import schwab.auth

    calls: list[str] = []
    monkeypatch.setattr(schwab.auth, "easy_client", lambda **_: calls.append("client"))
    monkeypatch.setattr(execution.equity_stream.SchwabEquityQuoteStream, "start", lambda *_: calls.append("stream"))
    before = {thread.ident for thread in threading.enumerate()}
    module = importlib.import_module("phase3_monitor")
    assert module.client is None
    assert module.ENGINE_MODULE is None
    assert calls == []
    assert {thread.ident for thread in threading.enumerate()} == before


def test_bounded_runner_uses_injected_runtime_and_never_sleeps(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    initialized: list[bool] = []
    sleeps: list[float] = []
    monkeypatch.setattr(module, "get_candles", lambda: pd.DataFrame())
    module.run_monitor(max_cycles=1, runtime_initializer=lambda: initialized.append(True), sleep_fn=sleeps.append)
    assert initialized == [True]
    assert sleeps == [module._cycle_sleep_seconds()]


def test_direct_entrypoint_calls_monitor_runner() -> None:
    tree = ast.parse((REPO_ROOT / "phase3_monitor.py").read_text(encoding="utf-8"))
    guards = [node for node in tree.body if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)]
    assert any(any(isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and getattr(item.value.func, "id", None) == "run_monitor" for item in guard.body) for guard in guards)