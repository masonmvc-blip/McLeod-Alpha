# McLeod Alpha Research Report: 2025-09-24 Trading Room — Post 41690

## Executive Assessment

The downside OMG in October 3 664 puts completed `5.23` to `5.54`.
A September 26 663-put 360 trade completed `2.29` to `2.61`, with a
source-reported `$950` net on 30 simulated contracts. The presenter then added
664 puts at `5.29`; the source does not cleanly reconcile this lot with the OMG
exit. A later October 3 663-put trade entered `5.23`, targeted `5.41`, and
remained adverse and open. The co-host's September 26 667 calls carried from
September 23 at a `2.985` average also remained unresolved.

## Source and Context

- Post `41690`; Vimeo `1121607061` (`9-24 TR`), `01:13:44`.
- Complete authorized VTT: 1,686 cues, `00:00:00-01:13:38`.
- Player stayed paused at `00:00`, at `0%` volume; no audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.
- Fed-policy uncertainty preceded new-home-sales data; SPY broke the downside
  OMG after a five-minute close and one-minute confirmation.

## Evidence Timeline

| Time | Evidence | Classification |
| --- | --- | --- |
| 00:20:26-00:28:59 | Oct. 3 664-put OMG `5.23` to `5.54`. | completed |
| 00:21:16-00:29:51 | Sep. 26 663-put 360 trade `2.29` to `2.61`. | completed |
| 00:28:13 | Additional 664 puts entered `5.29`. | reconciliation ambiguous |
| 00:41:50-00:55:44 | Oct. 3 663 puts `5.23`, target `5.41`, later 25-30 cents adverse. | unresolved |
| 00:57:31-terminal | Sep. 26 667 calls averaged `2.985`; loss expected. | unresolved carry |

## Actionable Research Lessons

1. Added lots require lot-specific exits; an OMG exit cannot silently close
   every same-direction position.
2. A completed intraday trade does not offset an unresolved carry in the
   ledger.
3. Post-news re-entry needs an independent invalidation.
4. Theta awareness arrived only after the averaged calls were deeply adverse.

## Falsifiable Hypotheses

1. Lot-level order IDs eliminate exit ambiguity.
2. No same-strike re-entry after an OMG reduces overexposure.
3. Forced terminal marking lowers reported session performance.
4. Maximum holding periods reduce expiration-week decay.

No broker ledger, sizes for every lot, terminal fills, independent P&L,
executable option paths, synchronized charts, Greeks, MFE/MAE, spreads,
slippage, fees, or full visual review is available.

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
