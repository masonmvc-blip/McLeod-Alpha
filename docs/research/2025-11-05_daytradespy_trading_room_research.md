# McLeod Alpha Research Report: 2025-11-05 Trading Room — Post 42195

## Executive Assessment

The formal November 14 675-put OMG was reported at `3.66` with a `4.18`
target. It traded near `4.10`, reversed, and remained open at recording end;
it is not counted as a win. The same sequence included an execution error:
one presenter bought calls instead of the intended puts at `3.66` and sold
them at `3.99`.

Both presenters then bought November 14 676 calls at `7.29`. One exited at
`7.45`; the other reported fills at `7.51` and `7.60`. A later November 14
678-call scalp entered at `6.70` and exited at `6.53`, a reported `0.17` loss.

## Source and Context

- Post `42195`; Vimeo `1096350129`, title `11-5 TR`, `01:16:47`.
- Complete authenticated transcript: 495 contiguous cues,
  `00:00-01:16:29`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.
- Context: a pullback around the daily 20 EMA, rapid intraday reversal, and
  scheduled PMI releases.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 13:27-15:46 | Nov. 14 675-put OMG reported at `3.66`; target `4.18`. | formal OMG |
| 13:41-14:55 | Wrong-side call purchase at `3.66`, sold `3.99`. | execution-error scalp |
| 21:20-25:34 | OMG bid near `4.10`, reversed, and stayed open. | unresolved terminal |
| 29:35-32:37 | Nov. 14 676 calls `7.29`; exits `7.45`, `7.51`, and `7.60`. | completed scalps |
| 46:54-1:03:25 | Nov. 14 678 calls `6.70` to `6.53`. | completed loss |
| 1:10:53-end | Presenter retained puts into the afternoon. | unresolved position |

## Actionable Research Lessons

1. Execution-direction errors require a distinct event flag; their profitable
   outcome must not validate the intended signal.
2. A near-target quote is not a fill. The formal OMG needs a terminal source
   or ledger before outcome classification.
3. Two presenters sharing one entry are correlated observations, not two
   independent setups.
4. Discomfort-based exits should be replayed against explicit structural
   invalidation and time stops.

No broker ledger, quantities, formal-OMG terminal exit, executable option
paths, Greeks, MFE/MAE, spreads, slippage, fees, or full visual review is
available.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
