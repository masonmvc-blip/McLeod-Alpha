# McLeod Alpha Research Report: 2025-09-09 Trading Room — Post 41547

## Executive Assessment

September 9 was dominated by a pending annual payroll revision and choppy trade
around the August pitchfork midline. The downside OMG bought September 12 649
puts at `3.23`, endured an adverse move after the news, and eventually reached
the `3.42` target; the presenter reported the fill at `3.46`.

While the put remained open, the presenter also bought September 12 649 calls
at `3.43` and sold `3.61`. This profitable counter-direction scalp temporarily
created opposing exposure rather than reducing the original put. The published
pick was reported successful but its entry and exit were not stated.

## Source Lineage and Evidence Quality

- Post `41547`; Vimeo `1117202192` (`9-9 TR`), duration `01:31:04`.
- Complete authorized VTT: 1,647 cues, `00:00:00-01:27:24`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Downside and upside OMG boundaries were `648.75` and `649.77`.
- The annual payroll revision was expected during the room and reported near
  negative `911,000`.
- Price repeatedly crossed the August pitchfork midline in a narrow range
  before a delayed downside break.
- The presenter waited roughly 30 minutes before initiating the OMG.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:08:15-00:14:31 | Published 649-put pick discussed; member reported 6%, but presenter terms were absent. | Modeled/source-reported pick only. |
| 00:33:01-00:34:22 | Downside OMG confirmed; Sep. 12 649 puts filled `3.23`, target `3.42`. | Position opened immediately before news. |
| 00:34:31-00:36:15 | Presenter acknowledged the bounce and said more confirmation would have improved entry. | Entry-timing self-critique. |
| 00:47:23-00:49:00 | With OMG puts still open, Sep. 12 649 calls entered `3.43`, sold `3.61`. | Completed counter-direction scalp. |
| 00:50:41-00:51:08 | OMG puts quoted near `2.74`. | Material adverse excursion, exact path unavailable. |
| 01:09:28-01:11:10 | Puts recovered; target reached and presenter reported exit `3.46`. | Completed source-reported OMG. |
| 01:16:02-01:24:59 | Further downside analysis was discussed but no additional fill was reported. | Analysis only. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250909-P41547-T01 | Published Sep. 12 649-put pick | terms unavailable | reported successful; members cited 6% |
| DTS-20250909-P41547-T02 | Sep. 12 649 puts; downside OMG | `3.23` | target `3.42`; reported fill `3.46` |
| DTS-20250909-P41547-T03 | Sep. 12 649 calls; counter-direction scalp | `3.43` | `3.61` |
| DTS-20250909-P41547-T04 | Later 648-put idea | no fill | `NO_TRADE` |

## Entry and Exit Lessons

1. Scheduled data should be an explicit entry gate, not an after-the-fill
   caveat.
2. A profitable terminal exit does not erase the observed adverse excursion.
3. Opposing positions should be treated as gross exposure, not assumed hedges.
4. Waiting for confirmation can materially improve entry quality.
5. Modeled picks must remain separate from presenter fills.

## Contradictions and Process Risks

- The OMG was entered immediately before scheduled news despite the presenter
  saying he disliked doing so.
- The put fell from `3.23` to about `2.74` before recovering.
- A call scalp was opened while the downside OMG remained active.
- The final recap emphasized completed wins without quantifying the interim
  drawdown or aggregate exposure.

## Falsifiable Replay Hypotheses

1. A scheduled-news exclusion window improves OMG risk-adjusted returns.
2. One-minute confirmation after a five-minute close reduces false entries.
3. Closing or reducing the original position before a counter-direction trade
   lowers gross-exposure drawdown.
4. MAE-aware scoring distinguishes resilient winners from low-risk winners.
5. Broker-fill reconciliation validates favorable target slippage.

## Ledger and Instrumentation Gaps

No full visual review, published-pick fills, broker/simulator orders,
independent P&L, exact sizes, executable option paths, aggregate opposing
exposure, synchronized bars, Greeks, full MFE/MAE, spreads, slippage, or
complete fees is available.

## Explicit Non-Changes

No live OMG, news-window, confirmation, hedging, sizing, direction, or
risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
