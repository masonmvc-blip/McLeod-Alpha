# McLeod Alpha Research Report: 2025-05-23 Trading Room

## Executive Assessment

The opening recovery produced profitable calls, but the recording also shows
how rapidly duplicate exposure accumulates when several versions of the same
idea are entered. May 30 576 calls entered at `7.34` and sold at `7.74`.
Later, May 30 577 calls entered at `7.03` after a 50% retracement/double-bottom
setup and reportedly filled their `7.54` exit after the breakout.

At the same time, model 577 calls at `6.95`, real 577 calls at `6.91`, and an
OMG 577-call position at `7.19` overlapped. The OMG came within two cents of
its `7.62` target, but wide spreads and failure to hold above resistance left
it unresolved when the recording ended. The speaker promised to exit all
positions before the holiday weekend, but the source does not capture those
exits.

The strongest lesson is that valid directional alignment does not justify
stacking indistinguishable positions. A setup-level exposure cap and one
canonical exit plan would make performance measurable and prevent an initially
good call thesis from becoming an unreconciled book.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40353`; authenticated Vimeo asset `1087253340`, `TR May
  23.mp4`.
- Duration `01:12:18`; 518 recovered timestamped cues span
  `00:00:00-01:11:19`.
- Visual orders, broker evidence, synchronized SPY bars, and executable option
  paths remain unavailable.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Tariff headlines caused pre-market weakness, followed by a strong opening
  recovery.
- SPY repeatedly tested resistance around `578.20-578.50`, including the
  200-day moving average and Fibonacci levels.
- The tape built higher lows but failed repeatedly to hold above the key
  resistance before the recording ended.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:09:23-00:09:39 | The speaker said half of the prior-day puts had been retained, then sold the remainder at a captioned `9.74`. | The May 22 position crossed sessions; its exact economics cannot be reconciled from the caption alone. |
| 00:10:53-00:13:22 | Ten May 30 577 calls filled at `6.95`; real 577 calls filled at `6.91`; a different presenter's 576 calls entered at `7.34` and sold at `7.74`. | The directional read worked, but three similar positions were already active. |
| 00:14:28-00:16:50 | After the upside OMG close, May 30 577 calls filled at `7.19`, target `7.62`; premium reached about `7.60` but did not fill amid wide spreads. | Touching the underlying level did not guarantee an executable option exit. |
| 00:28:18-00:32:51 | Price retraced to the 50% level and moving-average support; a double bottom and renewed close above resistance were identified before another 577-call entry at `7.03`. | This was the most clearly confirmed admission of the session. |
| 00:44:02-00:45:55 | SPY touched the expected resistance, but option premium lagged; the presenters explicitly confused which trade should have exited. | Overlapping contracts degraded real-time state awareness. |
| 00:51:46-00:52:39 | SPY broke resistance; the `9:51` 577-call trade reportedly filled, consistent with its `7.54` target. | Confirmation plus structural room produced the cleanest later trade. |
| 00:57:06-01:00:33 | Back-and-forth price action eroded premium and the option lagged brief underlying pushes. | Premium targets must be tested with bid/ask paths, not spot touches. |
| 01:03:59-01:10:43 | The speaker said every trade would be closed before the holiday weekend; the `7.19` OMG and `6.95` model calls were still open at recording end. | The stated time stop is sensible but not observed or auditable here. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250523-T01 | Residual May 22 puts carried overnight | Prior-day entry `6.48` | Remaining half sold; captioned premium `9.74`, attribution uncertain |
| DTS-20250523-T02 | Ten May 30 577 calls; model recovery | `6.95` | Unresolved |
| DTS-20250523-T03 | May 30 576 calls; opening recovery | `7.34` | `7.74` |
| DTS-20250523-T04 | Real May 30 577 calls | `6.91` | Unresolved |
| DTS-20250523-T05 | May 30 577 calls; upside OMG | `7.19` | Unresolved; target `7.62` |
| DTS-20250523-T06 | May 30 577 calls; 50% retracement recovery | `7.03` | Reported filled at target `7.54` |

Participant results, the published pick, and unfilled ideas are excluded.

## Entry and Exit Lessons

1. The best later entry waited for a completed retracement, support hold, and
   renewed break.
2. An underlying touch is not an option fill; executable bid and spread govern
   the exit.
3. One directional thesis should have one aggregate risk budget across real,
   model, and OMG variants.
4. A weekend time stop is useful only if its actual fill is logged.
5. If presenters cannot immediately identify which position hit, the trade
   inventory is already too complex.

## Contradictions and Process Risks

- Several near-identical 577-call positions had different entries and mutable
  targets without a single aggregate exposure view.
- The OMG nearly reached target, but no rule converted a near-fill into a
  reduced target or partial exit.
- Confidence increased while price repeatedly failed to hold the same
  resistance.
- A commitment to close by day end was not captured as an executed action.
- The prior-day put exit premium is ambiguous and cannot be treated as
  verified P&L.

## Falsifiable Replay Hypotheses

1. Permit only one open position per direction/setup family unless aggregate
   risk remains below a predetermined cap.
2. Compare the opening anticipatory calls with the later
   retracement-and-rebreak entry.
3. Replace premium targets with executable bid-based targets and measure
   missed-fill frequency.
4. Enforce and timestamp a Friday cutoff for every unresolved intraday option.

## Ledger and Instrumentation Gaps

No broker orders, exact sizes for all trades, executable bid/ask history, fees,
MFE/MAE, aggregate Greeks, account-mode identifiers, or day-end fills exist.
The prior-day put resolution and presenter attribution remain uncertain.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, hedging, expiration, or risk-policy
change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
