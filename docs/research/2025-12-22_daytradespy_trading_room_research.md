# McLeod Alpha Research Report: 2025-12-22 Trading Room — Post 42820

## Executive Assessment

The formal December 26 683-put OMG entered at `2.33` with a `2.47` target but
remained open near `2.29-2.32` late in the recording. A separate 683-put scalp
entered about `2.62` and was sold at prior-low support within 18 seconds, but
the exit premium is absent.

An intended put order became a call because the platform repeatedly selected
the wrong side; the accidental call was sold for a reported 12-cent gain and
was explicitly logged as a mistake. A December 26 684-call scalp entered
`3.11` and also remained open, later quoted near `2.51-2.53`. Older puts
carried from Friday remained adverse and unresolved.

## Source and Context

- Post `42820`; Vimeo `1148729287`, title `TR Dec 22`, `01:10:17`.
- Complete authenticated caption track: 1,377 native VTT cues,
  `00:00:00.000-01:09:50.025`.
- Player remained muted, paused, and at `00:00`; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 10:09-end | Dec. 26 684 calls entered `3.11`; no terminal exit. | unresolved call |
| 20:42-22:38 | Intended put order became an accidental call; sold for reported 12 cents. | execution error |
| 24:53-end | Formal Dec. 26 683-put OMG entered `2.33`, target `2.47`; no exit. | unresolved OMG |
| 49:00-49:52 | Separate 683 puts near `2.62`, sold after 18 seconds; exit missing. | incomplete completed scalp |
| End | Friday puts and current calls/puts all remained open. | unresolved inventory |

## Actionable Research Lessons

1. A side-selection confirmation interlock is necessary before order submit.
2. Accidental profits remain execution errors, not strategy wins.
3. Low volatility and a short week justified lowering call expectations but
   did not convert an unfilled target into a result.
4. Overlapping call and put inventory requires a unified terminal ledger.

No quantities, exact accidental-order fills, separate put exit, terminal
fills, executable paths, Greeks, MFE/MAE, fees, or visual review exists.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
