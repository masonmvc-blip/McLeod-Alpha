# McLeod Alpha Research Report: 2025-11-18 Trading Room — Post 42367

## Executive Assessment

The formal November 21 663-call OMG was reported from `6.93` to its `7.35`
target. Two rapid discretionary 663-call scalps were reported at `6.98` to
`7.30` and `6.84` to `7.10`.

Those wins do not describe the whole session. A Cloudflare/data-feed failure
caused delayed and retrospectively adjusted candles, an anomalous SPY print,
and apparently distorted option fills. November 21 662 calls entered at `7.42`,
663 calls entered at `6.81`, and later 659 calls entered at `7.58` remained
unresolved and impaired when the recording ended. Prior 685 calls with a
reported `6.10` basis were still open near `0.22`.

## Source and Context

- Post `42367`; Vimeo `1138555020`, title `11-18 TR`, `01:23:41`.
- Complete authenticated transcript: 589 contiguous cues,
  `00:00-01:23:33`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.
- Context: a brief upside breakout, severe feed distortion, a seven-point SPY
  air pocket, and a partial rebound.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 13:15-16:39 | Formal Nov. 21 663 calls reported `6.93` to `7.35`. | completed OMG |
| 14:52-16:07 | Nov. 21 663 calls reported `6.98` to `7.30`. | completed scalp |
| 17:57-18:54 | Nov. 21 663 calls reported `6.84` to `7.10`. | completed scalp |
| 23:22-42:25 | 662 calls `7.42` and 663 calls `6.81` became impaired amid feed errors. | unresolved positions |
| 48:37-49:00 | A 659-put idea was rejected because volatility and spread were extreme. | explicit no-trade |
| 1:00:52-end | 659 calls `7.58` remained open; prior 685 calls remained deeply impaired. | unresolved positions |

## Actionable Research Lessons

1. Feed integrity is a hard evidence gate: candles, fills, and option marks
   observed during a known outage cannot support clean execution statistics.
2. Rapid completed winners and unresolved losing inventory require one ledger;
   reporting only closed scalps creates survivorship bias.
3. A formal breakout can meet its target even when the triggering candle is
   later adjusted. That makes the result operationally non-reproducible until
   an independent timestamped feed is replayed.
4. Rejecting the high-volatility put was disciplined; opening new calls while
   the feed remained suspect was inconsistent with the stated risk concern.

No broker ledger, quantities, cancellation rulings, executable paths, Greeks,
MFE/MAE, spreads, slippage, fees, or full visual review is available.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
