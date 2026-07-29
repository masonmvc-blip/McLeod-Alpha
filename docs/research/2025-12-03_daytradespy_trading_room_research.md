# McLeod Alpha Research Report: 2025-12-03 Trading Room — Post 42548

## Executive Assessment

The session paired a fast recovery thesis with repeated call scalps. The
presenter-reported December 5 680-call sequence completed `4.07` to `4.25` and
then `4.01` to `4.30`; a later December 5 682-call trade completed `3.02` to
`3.20`. A separate December 12 681-call simulator trade completed about
`7.00` to `7.23`.

The formal OMG lineage is not clean. At 20:11 the room specified December 12
681 calls, but the subsequent fill narration reverted to December 5 680 calls.
Later, the formal simulator order was explicitly reported not filled even
though attendees reported gains. This record therefore preserves the
contract conflict and does not convert the missed simulator order into a
presenter fill.

## Source and Context

- Post `42548`; Vimeo `1143153065`, title `12-3 TR`, `01:17:54`.
- Complete authenticated transcript: 501 contiguous cues,
  `00:01-01:17:35`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 09:39-22:00 | Dec. 5 680 calls reported `4.07` to `4.25`. | completed discretionary scalp |
| 20:11-22:53 | OMG narration alternated between Dec. 12 681 and Dec. 5 680 calls. | contract-lineage conflict |
| 22:42-40:29 | Dec. 5 680 calls reported `4.01` to `4.30`. | completed discretionary scalp |
| 34:17-50:19 | Formal OMG simulator order remained unfilled; attendee fills were discussed separately. | queued, not presenter-filled |
| 44:39-1:11:09 | Dec. 5 682 calls reported `3.02` to `3.20`. | completed discretionary trade |
| 54:58-56:37 | Dec. 12 681 simulator calls reported about `7.00` to `7.23`. | completed simulator scalp |

## Actionable Research Lessons

1. A triggered signal is not an executed presenter trade when the simulator
   explicitly fails to fill.
2. Contract identity must be locked at entry; the 681/680 and Dec. 12/Dec. 5
   narration cannot be silently reconciled.
3. The repeated small-profit method worked here, but it increased transaction
   count and depended on a persistent recovery.
4. Target changes from `3.25` to `3.20` show why final executed exits, not
   preliminary orders, belong in outcome statistics.

No quantities, broker ledger, exact attribution for every voice, executable
option paths, Greeks, MFE/MAE, spreads, slippage, fees, or full visual review
exists.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
