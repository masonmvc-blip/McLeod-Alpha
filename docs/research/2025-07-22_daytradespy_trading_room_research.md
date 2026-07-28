# McLeod Alpha Research Report: 2025-07-22 Trading Room — Post 41007

## Executive Assessment

July 22 was a choppy reversal session shaped by Powell commentary, earnings,
Richmond Fed data, and GM news. A real July 25 630-call scalp entered at `2.32`
and exited at `2.45`; the challenge version entered at `2.29` and exited at
`2.63`. A separate real July 25 629-call position entered at `3.12` and had no
evidenced terminal exit.

The downside OMG was correctly treated as no trade when one-minute
confirmation failed. Later commentary that it “would've worked” is a
counterfactual, not a reportable win. A discretionary July 25 627-put event
scalp entered at `3.20` just before Richmond Fed data and exited at `3.36`.
That favorable result does not remove the governance risk of initiating
exposure immediately before a scheduled release.

## Source Lineage and Evidence Quality

- Day Trade SPY post `41007`, published July 22, 2025.
- Authenticated Vimeo asset `1103574684`, title `7-22 TR`, duration
  `01:11:44`.
- Complete authorized English auto-generated VTT: 1,425 cues span
  `00:00:00-01:11:18`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Powell remarks, large-company earnings, Richmond Fed data, and GM news
  contributed to fast reversals.
- Approximate OMG boundaries were `629.51` upside and `628.77` downside.
- The early downside close lacked one-minute confirmation, after which the
  room shifted to discretionary calls and an event-driven put scalp.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:11:25-00:15:15 | Real July 25 630 calls entered `2.32` and exited `2.45`. | A completed short call scalp. |
| 00:13:00-00:17:57 | Twenty challenge 630 calls entered `2.29` at 9:35 and exited `2.63` at 9:40. | Same-contract real and challenge positions should be aggregated. |
| 00:16:43 onward | Real July 25 629 calls entered `3.12`, initially targeting about `3.25`. | No terminal exit was evidenced; later repair discussion implies unresolved adverse exposure. |
| 00:17:17 | The downside OMG lacked confirmation and was declared effectively dead/no formal trade. | The operational record is `NO_TRADE`, regardless of later price movement. |
| 00:37:24-00:38:52 | July 25 627 puts entered `3.20` before Richmond Fed data and exited `3.36`. | The winning outcome followed an event-window entry with gap/slippage risk. |
| later recap | Published call pick was reconstructed near `2.42` at 9:31 with a `2.57` target reached at 9:38; the strike was not unambiguously preserved in the transcript. | Preserve the missing strike rather than infer it from adjacent discussion. |
| terminal room | Call repair was conditioned on a break and hold above resistance; no such confirmed repair or exit was narrated for the `3.12` calls. | The position remains unresolved in the source record. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250722-P41007-T01 | July 25 630 calls; real scalp | `2.32` | `2.45` |
| DTS-20250722-P41007-T02 | July 25 630 calls; challenge, 20 contracts | `2.29` | `2.63` |
| DTS-20250722-P41007-T03 | July 25 629 calls; real position | `3.12` | unresolved; initial target about `3.25` |
| DTS-20250722-P41007-T04 | July 25 627 puts; discretionary event scalp | `3.20` | `3.36`; target `3.35` |
| DTS-20250722-P41007-T05 | July 25 call; retrospectively modeled published pick, strike unavailable | modeled `2.42` | modeled target `2.57` reached |

## Entry and Exit Lessons

1. A failed confirmation produces a no-trade record; later favorable movement
   must remain a counterfactual.
2. Aggregate challenge and real positions when they use the same contract and
   timing.
3. Scheduled-event entries need an explicit event window, maximum slippage,
   and gap-risk policy.
4. An unresolved trade cannot be repaired into a completed outcome without an
   evidenced fill.
5. Preserve missing instrument fields rather than infer a strike from nearby
   commentary.

## Contradictions and Process Risks

- The formal downside OMG was skipped, then later described as though it would
  have succeeded.
- Challenge, real, and published call variants were directionally correlated.
- The `3.12` real call had no evidenced exit or quantified maximum loss.
- Puts were initiated immediately before a scheduled economic release.
- Real and simulated versions of the put trade were discussed without an
  aggregate position ledger.
- The published pick's exact strike is not transcript-verifiable.

## Falsifiable Replay Hypotheses

1. Lock failed-confirmation setups as `NO_TRADE` in the immutable signal log.
2. Deduplicate same-contract real and challenge call variants.
3. Exclude entries inside a predeclared economic-release blackout window.
4. Require terminal status for every entered position.
5. Reject any instrument record missing strike or expiration from contract-level
   expectancy analysis.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, quantities for real trades,
terminal exit for the `3.12` calls, exact pick strike, aggregate exposure,
synchronized bars, executable option paths, Greeks, MFE/MAE, spreads,
slippage, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, event-window, repair,
or signal-classification change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
