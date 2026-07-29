# McLeod Alpha Research Report: 2025-11-28 Trading Room — Post 42468

## Executive Assessment

No live room trade or formal OMG was taken. The presenters explicitly rejected
execution because the Black Friday half-day produced very low volume and
abnormally wide, unstable bid/ask spreads. Several paper-account orders filled
during a platform demonstration, but the presenter repeatedly said they were
not intended real trades and that the simulator was behaving unrealistically.

The published December 5 682-call pick was modeled at an average `4.83` entry.
Its `5.12` 6% target had not traded by the review at 43:05, although some
members reported smaller profits. It therefore was not claimed as a formal
6%-target success in-source.

## Source and Context

- Post `42468`; Vimeo `1142136522`, title `TR Nov 28`, `00:55:36`.
- Complete authenticated transcript: 373 contiguous cues, `00:00-00:54:42`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 12:13-24:01 | Calls and puts rejected because spreads were extreme. | explicit no-trade |
| 27:50-32:24 | No OMG; presenters warned not to trade the observed market. | formal abstention |
| 36:41-38:30 | Simulator demonstration orders filled unrealistically; no real intent. | paper-only demonstration |
| 41:57 | Formal OMG withdrawn. | no formal trade |
| 42:08-43:27 | Published 682-call pick modeled `4.83`; `5.12` target not reached yet. | incomplete published outcome |
| 48:43 | Room closed early because conditions remained unsuitable. | session abstention |

## Actionable Research Lessons

1. Spread/liquidity gates can correctly override a technically valid setup.
2. Simulator fills must never enter live-execution outcome statistics.
3. Member-reported profits do not establish that the modeled 6% pick target
   filled.
4. Short-session theta and exit-window constraints materially change risk.

No broker ledger, executable quote archive, later pick outcome, Greeks,
MFE/MAE, fees, or full visual review is available.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
