# McLeod Alpha Research Report: 2025-12-16 Trading Room — Post 42767

## Executive Assessment

The formal OMG was abandoned because its close coincided with scheduled PMI
data. The room instead reported three completed December 19 680-call trades:
`4.13` to `4.25` in about fourteen minutes, `3.84` to `4.10`, and `4.20` to
`4.30`. A later December 19 679-put trade completed `4.97` to `5.39`.

The published 680-put pick was reconstructed at an average `5.31` entry and
`5.62` target, reached before the room's reconstruction; it is not a
contemporaneous room fill. The final 677-put position entered at `4.80` and
remained open at recording end with a `5.16` target. Friday 690 calls also
remained adverse and unresolved.

## Source and Context

- Post `42767`, published December 17 for the December 16 recording.
- Vimeo `1147377514`, title `12-16 TR`, `01:17:17`.
- Complete authenticated caption track: 1,601 native VTT cues,
  `00:00:01.995-01:17:10.215`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 14:41-26:38 | Published 680-put pick reconstructed `5.31` to `5.62`. | modeled/published pick |
| 15:37-29:30 | Dec. 19 680 calls `4.13` to `4.25`. | completed call trade |
| 23:28-30:19 | PMI timing invalidated the formal OMG. | no-trade decision |
| 33:35-34:34 | Dec. 19 680 calls `3.84` to `4.10`. | completed call scalp |
| 36:07-38:31 | Dec. 19 680 calls `4.20` to `4.30`; source called it 13 cents. | completed call trade; arithmetic conflict |
| 54:21-56:58 | Dec. 19 679 puts `4.97` to `5.39`. | completed put trade |
| 1:15:36-end | Dec. 19 677 puts entered `4.80`, target `5.16`; no exit. | unresolved position |

## Actionable Research Lessons

1. Scheduled data at the signal close can invalidate an otherwise formal OMG.
2. A published pick reconstructed after its target was reached is modeled
   evidence, not an observed live fill.
3. Spread quality improved one strike out of the money; replay should test a
   maximum-spread gate rather than assume that relationship is stable.
4. Source arithmetic conflicts must remain visible: `4.20` to `4.30` is ten
   cents even though the presenter called it thirteen.
5. Never score the terminal 677 puts or carried 690 calls without later
   ledger evidence.

No quantities, unified broker ledger, executable option paths, Greeks,
MFE/MAE, fees, independent fills, or full visual review exists.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
