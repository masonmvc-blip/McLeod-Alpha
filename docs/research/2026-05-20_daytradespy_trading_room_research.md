# McLeod Alpha Research Report: May 20, 2026 Trading Room

## Scope and Evidence

Source recording: Day Trade SPY, "Trading Room Video Recording - May 20, 2026" (1:20:21). The Vimeo caption transcript was reviewed from the authenticated recording page. This is external qualitative research, not a live trading instruction.

## Observations

- The session carried elevated event context from NVIDIA earnings after the close and FOMC minutes later in the day. The room treated these as reasons for heightened uncertainty, not proof of an intraday directional outcome.
- The opening gap sold off sharply. Initial downside participation was discussed alongside a warning not to assume support would appear immediately; later decisions depended on whether price could reclaim moving averages and local structure.
- A fast reversal followed an undercut of a prior intraday low. The source characterized it as a shakeout-like move only after a strong recovery, high-volume response, and subsequent break through nearby resistance.
- Several attempted continuations failed at moving-average clusters or Fibonacci retracements. The discussion repeatedly distinguished an early entry from waiting for a test, a close, and a confirmed break.
- Option selection was explicitly constrained by volume and spread. The recording identified liquidity and changing premium behavior as reasons a technically plausible move might still be unsuitable for execution analysis.
- NVIDIA earnings options were described as high-volatility and expensive. The source raised post-event volatility compression as an execution risk and preferred observation of the post-event reaction over assuming the earnings direction.

## Research Implications

1. Tag earnings and scheduled-policy periods as `EVENT_WINDOW`; test structural behavior and spread cost independently before, during, and after those windows.
2. Define `STRUCTURAL_RECLAIM` after an undercut using recovery volume, a reclaim/hold, and a resistance break; compare it with entries triggered merely by a new low.
3. Measure the value of waiting for a post-break test against the opportunity cost of late confirmation, using executable bid/ask data rather than chart-only fills.
4. Add `OPTION_SPREAD_WIDE` and `EXECUTION_DATA_UNRELIABLE` gates to replay analysis when liquidity, premium behavior, or simulated fills diverge from the visible market context.

## Decision

No live entry, exit, stop, sizing, or directional policy changes. The useful output is a research-only agenda for event-window behavior, shakeout/reclaim confirmation, and option-execution gating.