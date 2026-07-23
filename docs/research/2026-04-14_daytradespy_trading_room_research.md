# McLeod Alpha Research Report: 2026-04-14 Trading Room

## Scope and Evidence

External qualitative research based on the authorized DayTradeSPY April 14, 2026 recording page (post 44382). The authorized Vimeo Transcript control was reviewed. This document retains synthesized evidence only, not source transcript content.

## Observations

- The session opened with a gap-up context, but the source framed the approach to pre-market resistance as an area requiring observation rather than immediate continuation.
- After an early upside surge, the room described a test-back and a transition into a one-minute trading range/pennant rather than a clean one-way breakout.
- A move near the 50 EMA and later bar-level confirmation were used as contextual checks; overhead resistance and the extent of the prior move constrained the bullish interpretation.
- The source explicitly treated lower participation as a weakness in the advance: a new high would need a reason and low-volume progress could be vulnerable to adverse news.
- Option-chain selection and rapidly widening spreads were discussed, so direction alone was not presented as sufficient for practical execution.

## Research Implications

1. Test a `GAP_UP_PREMARKET_RESISTANCE` label by conditioning an opening extension on distance to pre-market resistance, then measure whether it accepts above that area or rotates into range.
2. Require bar-close or hold confirmation after a surge and test whether low relative volume predicts failure to clear overhead structure; invalidate a continuation candidate on re-entry into the range.
3. Record chosen contract, bid, ask, spread, quote time, and fill state around the impulse before assigning execution value to a correct directional call.

## Decision

No live entry, exit, stop, sizing, direction, or other trading-policy change is authorized. This remains research-only: the source provides qualitative structure and liquidity commentary, not synchronized bars, full quotes, or validated outcomes.