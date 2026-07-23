# McLeod Alpha Research Report: May 15, 2026 Trading Room

## Scope and Evidence

Source recording: Day Trade SPY, "Trading Room Video Recording - May 15, 2026". The Vimeo caption transcript was reviewed from the authenticated recording page. This is external qualitative research, not a live trading instruction.

## Observations

- The week ended with a large overnight gap lower after a sharp prior rally. The room recognized the drop as a materially different regime and watched whether opening support would hold before treating the move as either continuation or recovery.
- The initial downside opening-range break reached a nearby structural support zone quickly. A short downside move was followed by indecision, competing support and resistance, and eventually a recovery through clustered moving averages.
- The transcript shows explicit premise reassessment: once the downside premise stalled near support and upside structure improved, the room shifted attention to the recovery instead of assuming the original break remained valid.
- The recovery was evaluated by moving-average reclaim, Fibonacci retracement, volume improvement, and whether price could sustain above the opening area. It then extended sharply through multiple retracement levels before consolidating.
- Option execution was a prominent constraint. The source discussed spread, implied volatility, time decay, and the increased cost of holding a short-dated position across a weekend; this reinforces the need to model realized execution rather than price direction alone.

## Research Implications

1. Add a `GAP_DISPLACEMENT` research flag and test whether opening-break continuation weakens when price reaches a known support zone immediately after a large overnight move.
2. Define `PREMISE_FAILURE` as a failed breakdown followed by a moving-average reclaim and improved volume; compare it with static continuation handling in replay only.
3. Track `STRUCTURAL_RECLAIM`, `FAST_DISPLACEMENT`, and `NO_ADMISSION` around the opening range, including time spent in indecisive congestion.
4. Persist implied volatility, theta exposure, bid, ask, spread, and holding horizon to assess whether a technically correct directional thesis was executable.

## Decision

No live entry, exit, stop, sizing, contract-selection, or weekend-holding policy changes. The research output is a gap-recovery and premise-failure study with execution-cost instrumentation.