# McLeod Alpha Research Report: 2025-08-05 Trading Room — Post 41171

## Executive Assessment

August 5 opened range-bound after Monday's rebound. A downside OMG boundary
close failed one-minute confirmation and was explicitly removed. The published
August 8 633-call pick was modeled from `2.74` to `3.10`.

Personal call scalps completed at `3.36` to `3.50`, `3.63` to `3.75`, and
`3.06` to `3.18`. A short-fuse 632-put trade entered `3.30` before the 10:00
services report and exited at `3.85`, far beyond its initial `3.42` target.
The challenge's 25 August 8 633 calls entered `2.91` but fell near `2.00` and
remained open; personal 632 calls entered at `3.17` also remained open near
`2.35`.

## Source Lineage and Evidence Quality

- Post `41171`; Vimeo `1107459984` (`8-5 TR`), duration `01:16:31`.
- Complete authorized VTT: 1,525 cues, `00:00:02-01:16:29`.
- Player stayed paused; volume was set to minimum; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Tariff headlines, expected rate cuts, and strong earnings framed the session.
- OMG boundaries were approximately `632.15` upside and `631.33` downside.
- SPY initially bounced, then sold sharply after ISM services printed `50.1`
  versus `51.5` expected.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:15:43-00:18:35 | Real 632 calls entered `3.36`, exited `3.50`; challenge 633 calls entered `2.91`. | Personal scalp completed while challenge stayed open. |
| 00:16:39-00:22:13 | Downside OMG closed but failed confirmation and was declared off. | Correct formal result is `NO_TRADE`. |
| 00:19:24-00:25:31 | Second real 632-call scalp entered `3.63`, exited `3.75`; 633 calls entered `3.06`, exited `3.18`. | Two more completed call scalps. |
| 00:30:20 | Published 633-call pick modeled `2.74` to `3.10`. | Modeled result is distinct from challenge entry. |
| 00:36:14-00:39:44 | 632 puts entered `3.30`, initial target `3.42`, exited `3.85` after weak services data. | Event exposure produced an outsized favorable fill. |
| 00:39:57-01:10:28 | 632 calls entered `3.17`; both these and challenge 633 calls deteriorated and remained open. | Two losing calls lacked terminal fills. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250805-P41171-T01 | August 8 632 calls; real scalp 1 | `3.36` | `3.50` |
| DTS-20250805-P41171-T02 | August 8 633 calls; challenge, 25 contracts | `2.91` | unresolved; near `2.00` at room end |
| DTS-20250805-P41171-T03 | August 8 632 calls; real scalp 2 | `3.63` | `3.75` |
| DTS-20250805-P41171-T04 | August 8 633 calls; real scalp | `3.06` | `3.18` |
| DTS-20250805-P41171-T05 | Published August 8 633-call pick; modeled | `2.74` | `3.10` |
| DTS-20250805-P41171-T06 | August 8 632 puts; short-fuse discretionary | `3.30` | `3.85`; initial target `3.42` |
| DTS-20250805-P41171-T07 | August 8 632 calls; real scalp 3 | `3.17` | unresolved; near `2.35` |
| DTS-20250805-P41171-T08 | Formal downside OMG | no fill | `NO_TRADE`; confirmation failed |

## Entry and Exit Lessons

1. Preserve confirmation failure as no trade even if the later path would win.
2. Pre-news option positions need explicit event-risk governance.
3. Score the initial target and event-driven realized exit separately.
4. Repeated successful scalps do not justify leaving later calls unmanaged.
5. Modeled pick and challenge fills must not be merged.

## Contradictions and Process Risks

- The presenter entered upside challenge calls while the downside OMG close was
  still being evaluated.
- The put was held directly into scheduled data without a stated maximum loss.
- Hindsight noted that the challenge should have been sold while profitable.
- The challenge rules said to stop at target unless “on a roll,” allowing
  discretionary overtrading.
- Two call positions remained substantially underwater and potentially became
  overnight holds.

## Falsifiable Replay Hypotheses

1. Enforce confirmation before formal OMG entry/scoring.
2. Compare pre-news holds with exits before the release.
3. Preserve original and realized targets as separate counterfactuals.
4. Stop new entries after the daily objective is reached.
5. Require terminal orders for all remaining calls.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, complete quantities outside the
challenge, terminal call fills, event-time executable path, aggregate
premium/Greeks, synchronized bars, MFE/MAE, spreads, slippage, or complete fees
is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, confirmation,
event-risk, repeated-scalp, overnight-hold, or aggregate-risk change is
authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
