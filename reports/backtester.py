"""Retired standalone backtest report script.

The historical replay stack now delegates entry and management policy to Brain.
This module intentionally contains no independent trading policy.
"""

RETIRED_MESSAGE = (
    "reports/backtester.py is retired. Use the Brain-backed replay and "
    "validation commands instead."
)


def main() -> None:
    raise SystemExit(RETIRED_MESSAGE)


if __name__ == "__main__":
    main()