# McLeod Alpha Research Report: 2025-11-07 Trading Room — Post 42218

## Executive Assessment

The formal November 14 667-put OMG entered at `6.98`, targeted `7.40`, and
reported a `7.50` fill roughly one minute later. The separately reviewed
published 667-put pick used a modeled `6.46` average and reported a `6.85`
fill; it must remain a separate lineage.

Completed presenter trades included November 14 667 calls `6.58` to `6.85`,
November 14 667 calls `6.63` to `6.85`, a 665-call scalp `7.52` to `7.70`,
and November 14 666 puts `6.90` to `7.02`. Another 667-call position entered
at `6.90` was partially filled near `6.91` and the remainder sold at `6.92`.
The source also reports a 666-put exit at `7.45`, but the entry premium is not
recoverable from the captions.

## Source and Context

- Post `42218`; Vimeo `1134694078`, title `TR Nov 7`, `01:19:16`.
- Complete authenticated transcript: 535 contiguous cues,
  `00:00-01:18:14`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.
- Context: heavy institutional selling, a test of the daily 50 EMA, high
  short-dated volatility, and wide spreads.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 12:48-15:22 | Nov. 14 667-put OMG `6.98` to `7.50`, target `7.40`. | completed OMG |
| 31:44-36:03 | Nov. 14 667 calls `6.58` to `6.85`. | completed scalp |
| 45:12 | 666 puts sold `7.45`; entry unavailable. | partial lineage |
| 47:39-48:36 | 665 calls `7.52` to `7.70`. | completed scalp |
| 57:48-59:20 | Nov. 14 667 calls `6.63` to `6.85`. | completed scalp |
| 1:00:33-1:05:08 | 667 calls `6.90`; partial near `6.91`, rest `6.92`. | completed managed trade |
| 1:03:23-1:04:11 | Published 667-put pick modeled `6.46` to `6.85`. | separate published lineage |
| 1:12:35-1:16:54 | Nov. 14 666 puts `6.90` to `7.02`. | completed scalp |

## Actionable Research Lessons

1. Formal OMG, published-pick modeling, and presenter execution need separate
   denominators even when contract direction and strike overlap.
2. Fast target overshoots can make reported fills plausible but still require
   executable quote replay.
3. Partial fills must preserve their management sequence rather than collapse
   into a single idealized exit.
4. Daily-50-EMA tests plus elevated volatility define a distinct regime for
   later replay, not immediate live authorization.

No broker ledger, quantities, executable paths, Greeks, MFE/MAE, contemporaneous
spreads, slippage, fees, or full visual review is available.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
