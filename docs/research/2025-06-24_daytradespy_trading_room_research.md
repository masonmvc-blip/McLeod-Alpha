# McLeod Alpha Research Report: 2025-06-24 Trading Room

## Executive Assessment

June 24 reinforces two opposing lessons. First, the room correctly refused to
declare an OMG trade because price touched and oscillated around the levels but
never produced the required close. In a choppy, news-sensitive session, that
strict definition prevented a marginal signal from becoming a trade.

Second, calls were still entered outside that formal setup. Early June 27 605
calls produced source-reported gains, and a later June 27 604-call recovery
trade entered `3.69` after a 50-EMA/retracement reclaim and sold at its `3.89`
target. Those were bounded. But model and real June 27 606 calls entered around
`2.97/3.03` remained underwater and unresolved while their target expanded
from approximately `3.20` to `3.95`.

The room also closed heavy June 27 600 calls at `6.15`, apparently resolving
the June 18 carry entered at `6.07`, though the recording does not prove that
the lot and size were unchanged. The best lesson is to keep the strict signal
definition and apply the same discipline to discretionary entries: target
expansion cannot replace invalidation when a trade moves adversely.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40708`; authenticated Vimeo asset `1096026987`, `6-24 TR`.
- Duration `01:10:17`; 453 timestamped cues span `00:00:00-01:09:59`.
- Complete authorized transcript; the recording remained muted throughout review.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Ceasefire headlines and Powell-related news created gap and reversal risk.
- Price repeatedly touched the OMG boundaries without a qualifying close.
- The session alternated between recovery attempts and congestion.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:07:39-00:07:50 | Heavy June 27 600 calls sold `6.15`. | Likely resolution of the June 18 carry, but lot identity is not proven. |
| 00:13:07-00:13:56 | Twenty model June 27 605 calls entered `3.22`; real 605 calls entered `3.34`. | Early discretionary recovery entries. |
| 00:17:43-00:17:54 | Model calls sold `3.45`; real calls sold `3.50`. | Both positions reached bounded exits. |
| 00:22:55-00:24:54 | Twenty model June 27 606 calls entered `2.97`; real calls entered `3.03`. | Later calls were admitted before a formal OMG signal. |
| 00:46:34-00:52:46 | A promotional put pick reached its target, but the room still said no OMG close had occurred. | Pick result does not convert the absent signal into a valid trade. |
| 00:55:23-00:56:22 | June 27 604 calls entered `3.69` after an inverted-head-and-shoulders/50-EMA/retracement reclaim; target `3.89`. | Multi-factor recovery entry with explicit target. |
| 01:02:06-01:03:12 | The 606 calls were near `2.67`; their target was raised to `3.95`. | Target expansion occurred while the trade was adverse. |
| 01:03:38 | The 604 calls sold `3.89`. | Planned target completed. |
| 01:08:00-01:09:59 | Model and real 606 calls remained open near recording end. | No audible resolution or formal invalidation. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250624-T00 | June 27 600 calls; heavy cross-session carry | prior session; June 18 source reported `6.07` | sold `6.15`; lot continuity unproven |
| DTS-20250624-T01 | 20 June 27 605 calls; model recovery | `3.22` | `3.45`; about `$450` net later reported |
| DTS-20250624-T02 | June 27 605 calls; real recovery | `3.34` | `3.50` |
| DTS-20250624-T03 | 20 June 27 606 calls; model | `2.97` | Open/unresolved; target expanded to `3.95` |
| DTS-20250624-T04 | June 27 606 calls; real | `3.03` | Open/unresolved; contract later narrated inconsistently |
| DTS-20250624-T05 | June 27 604 calls; recovery reclaim | `3.69` | `3.89` |

The put pick and viewer results are excluded from the presenter ledger.

## Entry and Exit Lessons

1. A line touch is not a close; preserving that distinction helps prevent
   signals in congestion.
2. Reclaimed support plus an explicit target produced a more auditable recovery
   trade than anticipatory entries.
3. A target should not be moved farther away merely because the position is
   underwater.
4. Every discretionary trade needs the same invalidation standard as the named
   setup it bypasses.
5. Cross-day carry identity must be reconciled by contract, quantity, fill, and
   broker order—not inferred only from narration.

## Contradictions and Process Risks

- The room correctly enforced the no-OMG close while still entering
  discretionary calls.
- The model 605-call entry was later recalled as `3.32/3.35`, conflicting with
  the initial explicit `3.22` fill.
- The real later call was initially identified as 606 but was later called 605
  before being identified again as 606.
- The 606-call target expanded from roughly `3.20` to `3.95` while premium fell.
- Both 606-call positions were unresolved at recording end.
- The apparent June 18 carry resolution lacks exact lot and size continuity.

## Falsifiable Replay Hypotheses

1. Compare line-touch entries against entries requiring a full qualifying close.
2. Require discretionary recovery trades to include a reclaimed level, one-bar
   hold, fixed invalidation, and minimum structural room.
3. Prohibit adverse target expansion; compare fixed-target/fixed-stop outcomes
   against the observed discretionary management.
4. Reconcile every carry across days with immutable trade IDs and quantities.

## Ledger and Instrumentation Gaps

No broker ledger, carry quantity, exact real quantities, synchronized bars,
visual pattern confirmation, bid/ask paths, MFE/MAE, complete commissions,
aggregate exposure, or later exits for the 606 calls exists.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, or risk-policy change
is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
