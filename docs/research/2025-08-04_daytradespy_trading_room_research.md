# McLeod Alpha Research Report: 2025-08-04 Trading Room — Post 41160

## Executive Assessment

SPY rebounded sharply after Friday's selloff. The formal August 8 626-call OMG
entered at `5.25` and exited at `5.57`. The published 626-call pick was modeled
from `4.70` to `4.98`, and the separate signal was modeled from a maximum
`5.40` entry to `5.67`.

The challenge bought 25 August 8 630 calls at `3.18`, but platform trouble
prevented a clearly narrated sale; the room booked a notional `3.38` exit.
Personal August 8 628 calls entered at `4.73`, partially exited `4.85`, and
finished at `4.94`. A late 629-call trade also exited profitably, but neither
entry nor exit premium was stated.

## Source Lineage and Evidence Quality

- Post `41160`; Vimeo `1107170483` (`TR Aug 4`), duration `01:10:11`.
- Complete authorized VTT: 1,365 cues, `00:00:00-01:09:50`.
- Player stayed paused; volume was set to minimum; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Futures rebounded after Friday's tariff/jobs-driven drawdown.
- OMG boundaries were approximately `625.86` upside and `624.82` downside.
- Persistent dip buying produced a near-continuous upside lifecycle.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:13:28-00:14:44 | Formal 626 calls chased from intended `5.01` to fill `5.25`; target `5.57`. | Slippage materially changed admission price. |
| 00:16:31-00:17:14 | Published 626 calls modeled `4.70` to `4.98`, target reached at 9:33. | Modeled result differs from OMG execution. |
| 00:21:37-00:24:19 | Twenty-five 630 calls entered `3.18`; platform did not accept the exit, so room “considered” sale at `3.38`. | Ledger result was not an evidenced terminal fill. |
| 00:32:47-00:36:06 | 628 calls entered `4.73`, partial `4.85`, remainder `4.94`. | Completed scaled exit with no quantity split. |
| 00:35:38-00:36:58 | OMG exited `5.57`; signal was separately modeled `5.40` to `5.67`. | Three 626-call accounting views must remain separate. |
| 00:59:25-01:05:18 | 629 calls entered and later filled out, but premiums were not narrated. | Directional success is attributable; P&L is not reconstructable. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250804-P41160-T01 | August 8 626 calls; formal OMG | `5.25` | `5.57` |
| DTS-20250804-P41160-T02 | Published August 8 626-call pick; modeled | `4.70` | `4.98` |
| DTS-20250804-P41160-T03 | August 8 630 calls; challenge, 25 contracts | `3.18` | notional `3.38`; platform fill unconfirmed |
| DTS-20250804-P41160-T04 | August 8 628 calls; discretionary | `4.73` | partial `4.85`, remainder `4.94` |
| DTS-20250804-P41160-T05 | August 8 626-call signal; modeled | max `5.40` | modeled `5.67` |
| DTS-20250804-P41160-T06 | August 8 629 calls; discretionary | unavailable | exited; premium unavailable |

## Entry and Exit Lessons

1. Score intended and actual chase entries separately.
2. Never treat a “considered” price as an executed fill.
3. Separate OMG, published-pick, and signal ledgers even for one contract.
4. Record partial quantities.
5. Missing premiums prevent expectancy reconstruction.

## Contradictions and Process Risks

- The OMG chased roughly 24 cents above the first intended price.
- Challenge profit was booked despite acknowledged platform failure.
- One 626-call contract family generated three different performance records.
- Partial-exit quantities were unavailable.
- The final 629-call trade lacked both premiums.

## Falsifiable Replay Hypotheses

1. Apply a maximum chase-slippage filter.
2. Exclude notional exits from realized P&L.
3. Separate OMG, pick, and signal expectancy.
4. Require quantity-weighted partial-exit accounting.
5. Reject trades lacking both entry and exit premiums from P&L statistics.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, confirmed challenge exit,
partial quantities, 629-call premiums, aggregate premium/Greeks, synchronized
bars, executable option paths, MFE/MAE, spreads, slippage, or complete fees is
available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, chase, partial-exit,
modeled-result, or ledger-accounting change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
