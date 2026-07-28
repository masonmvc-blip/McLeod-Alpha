# McLeod Alpha Research Report: 2025-09-25 Trading Room — Post 41700

## Executive Assessment

The September 26 655-put OMG completed `4.24` to `4.50`. A personal 657-put
scalp reportedly gained 40 cents, although its entry is only inferable as
approximately `2.85` from the stated gain and `3.25` exit. A September 26
657-call 360 trade completed `5.46` to `5.62`. A separate 657-call trade entered
`2.40` with a `2.60` objective but had no source-supported exit.

An October 3 655-put trade entered `4.81`, targeted `5.10`, and was explicitly
carried beyond the room. The co-host's September 26 667 calls, averaged `2.985`
since September 23, had decayed to roughly `0.17`; a sell order was mentioned
but no fill confirmed. Completed winners must not obscure these open losses.

## Source and Context

- Post `41700`; Vimeo `1121943308` (`TR Sept. 25`), `01:11:21`.
- Complete authorized VTT: 1,670 cues, `00:00:00-01:10:25`.
- Player stayed paused at `00:00`, at `0%` volume; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.
- A strong downside move reached the daily 20 EMA, then reversed sharply.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 00:14:05-00:15:32 | Sep. 26 655-put OMG `4.24` to `4.50`. | completed |
| 00:17:30-00:19:26 | Sep. 26 657-put scalp sold `3.25`, reported +`0.40`. | completed; entry inferred |
| 00:37:04-terminal | Oct. 3 655 puts `4.81`, target `5.10`; held. | unresolved |
| 00:40:50-00:43:09 | Sep. 26 657-call 360 trade `5.46` to `5.62`. | completed |
| 00:42:16-terminal | Sep. 26 657 calls `2.40`, target `2.60`. | unresolved |
| 01:08:38-terminal | Old 667 calls near `0.17`; sell order not confirmed. | unresolved large loss |

## Actionable Research Lessons

1. Every claimed gain needs an explicit entry, exit, and size.
2. Same-session reversal trades require independent IDs and exposure limits.
3. “Made up elsewhere” is not position-level reconciliation.
4. Expiration-day decay shows the cost of repeatedly postponing invalidation.

## Falsifiable Hypotheses

1. Entry-completeness filters lower scalp win counts.
2. A terminal liquidation rule reduces expiration decay.
3. Position-level accounting prevents winners from masking open losses.
4. Reversal exposure caps improve downside-to-upside transition risk.

No full visual review, complete pick terms, terminal fills, reliable ledger,
independent P&L, exact sizes, aggregate Greeks, executable option paths,
synchronized bars, MFE/MAE, spreads, slippage, or fees is available.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
