"""Retired legacy paper-trading runtime.

Paper execution was retired in favor of Brain-driven simulation and replay.
This module intentionally contains no entry, exit, or risk policy.
"""

RETIRED_MESSAGE = (
    "paper_trader.py is retired. Use backtesting.stop_policy_simulator or the "
    "Brain-backed replay tools instead."
)


def main() -> None:
    raise SystemExit(RETIRED_MESSAGE)


if __name__ == "__main__":
    main()