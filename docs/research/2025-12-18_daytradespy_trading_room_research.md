# McLeod Alpha Research Report: 2025-12-18 Trading Room — Post 42797

## Executive Assessment

The formal December 26 678-call OMG entered at `4.13`. Its option target was
stated as `4.38`; the caption later reports an OMG fill but renders the fill
price ambiguously as `4.30`. The record therefore preserves completion while
declining to invent the exact exit. A separate 678-call trade completed
`4.12` to `4.34`, followed by a December 19 677-call scalp `2.33` to `2.45`
and a December 26 678-call scalp `3.86` to `4.00`.

The prior day's 679 calls, averaged near `4.65`, were mistakenly sold at
`3.83`, an 82-cent arithmetic loss (the presenter called it 83 cents).
Two final positions remained open: December 26 678 calls at `4.73`, with
planned partial exits `5.06/5.35`, and December 26 680 calls at `3.58`, with
an intended exit near `3.90`.

## Source and Context

- Post `42797`, published December 19 for the December 18 recording.
- Vimeo `1148133596`, title `TR Dec 18`, `01:16:22`.
- Complete authenticated caption track: 1,667 native VTT cues,
  `00:00:02.105-01:15:45.935`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 10:46-20:16 | Prior-day 679 calls near `4.65` mistakenly sold `3.83`. | completed losing carryover; arithmetic conflict |
| 13:54-37:32 | Formal Dec. 26 678-call OMG `4.13`; completion stated, exact exit caption-conflicted. | completed OMG, exit ambiguous |
| 30:32-31:27 | Dec. 19 677 calls `2.33` to `2.45` in 37 seconds. | completed scalp |
| 33:02-36:40 | Dec. 26 678 calls `4.12` to `4.34`. | completed call trade |
| 1:00:19-1:01:17 | Dec. 26 678 calls `3.86` to `4.00` in 54 seconds. | completed scalp |
| 1:09:46-end | Dec. 26 678 calls `4.73` and 680 calls `3.58` remained open. | unresolved positions |

## Actionable Research Lessons

1. Narration plus order entry created a documented, costly execution mistake;
   replay should test a confirmation interlock before submission.
2. Do not silently repair caption ambiguity: preserve the OMG target, stated
   completion, and unknown exact fill as separate facts.
3. Same-direction overlapping calls require position-level identity; otherwise
   a later fill can be assigned to the wrong trade.
4. Wide put spreads correctly prevented a queued 676-put idea from becoming a
   trade when its event did not occur.
5. Terminal exit plans are not realized outcomes.

No quantities, unified broker ledger, exact OMG exit, terminal fills,
executable option paths, Greeks, MFE/MAE, fees, or full visual review exists.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
