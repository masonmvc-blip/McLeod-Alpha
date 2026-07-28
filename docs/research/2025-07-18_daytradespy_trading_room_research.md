# McLeod Alpha Research Report: 2025-07-18 Trading Room — Post 40972

## Executive Assessment

July 18 was an expiration-Friday session in which the formal downside OMG was
ultimately skipped, but several discretionary trades remained. Twenty July 25
630 challenge calls filled at `3.55` with a `3.75` target, while real 630 calls
filled at `3.52`. Both were unresolved at the terminal cue. The later published
pick retrospectively modeled the same 630 calls at `3.61` with a `3.82` target;
it also remained unresolved.

A July 25 628-put scalp entered at `3.70` and exited at `3.89`. A second
628-put scalp was queued after a moving-average rejection, but its entry premium
was not stated; it remained open with a `4.04` target. The room therefore ended
with opposing calls and puts, no aggregate exposure ledger, and no maximum-loss
rule. Operationally, the session also contained two near order-entry errors:
put-versus-call selection and 629-versus-630 strike selection.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40972`, published July 18, 2025.
- Authenticated Vimeo asset `1102571874`, title `TR July 18`, duration
  `01:12:52`.
- Complete authorized English auto-generated VTT: 1,673 cues span
  `00:00:00-01:12:29`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Expiration Friday involved about `$2.8T` of contracts, strong index futures,
  Michigan sentiment/inflation-expectation news, and repeated fast reversals.
- Approximate OMG boundaries were `629.36` upside and `628.65` downside.
- Price oscillated around both boundaries, jumped sharply on news, then moved
  into a lower-high/lower-low decline toward `627`.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:22:43-00:24:47 | A downside OMG close appeared, but one-minute confirmation failed; presenters deferred and later abandoned the setup. | Event-risk abstention avoided treating a boundary close as sufficient. |
| 00:24:48-00:28:48 | Twenty July 25 630 challenge calls eventually filled at `3.55`; an order ticket first showed puts and later the wrong 629 strike. | Manual ticket validation prevented two material order-entry errors. |
| 00:25:55-00:26:10 | Real July 25 630 calls filled at `3.52`. | Real and challenge exposure were highly correlated and should be aggregated. |
| 00:28:48-00:39:21 | Challenge target was `3.75`; presenters decided to wait through Michigan news and did not take the formal downside OMG. | Holding calls into news was discretionary, while the rule-based opposite trade was suppressed. |
| 00:46:22-00:47:43 | Same-day expiring calls were described as vulnerable to severe theta and holders were told to accept the loss. | The warning was directionally sound but lacked a quantified exit rule. |
| 01:01:06-01:03:54 | July 25 628 puts entered `3.70`, targeted `3.85`, and exited `3.89`. | A short, completed downside scalp followed support failure. |
| 01:06:20-01:11:01 | A second 628-put scalp was queued/treated as open with target `4.04`; no entry premium was narrated. | The incomplete ledger prevents return calculation. |
| 01:08:18-01:10:29 | Published July 25 630-call pick was reconstructed at `3.61`, target `3.82`; real calls were kept because a week remained. | Pick, challenge, and real calls represent one correlated thesis with different accounting. |
| 01:10:54-01:11:16 | Calls and puts were both held at the end because expiration volatility might let both targets fill. | Two-sided exposure was justified by possibility rather than an aggregate-risk rule. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250718-P40972-T01 | 20 July 25 630 calls; challenge | `3.55` | open; target `3.75` |
| DTS-20250718-P40972-T02 | July 25 630 calls; real position | `3.52` | open; later hold planned |
| DTS-20250718-P40972-T03 | July 25 628 puts; discretionary scalp 1 | `3.70` | `3.89`; target `3.85` |
| DTS-20250718-P40972-T04 | July 25 628 puts; discretionary scalp 2 | unavailable | open; target `4.04` |
| DTS-20250718-P40972-T05 | July 25 630 calls; retrospectively modeled pick | modeled `3.61` | unresolved; target `3.82`, EOD cancellation if unfilled |

## Entry and Exit Lessons

1. Validate side, strike, expiration, quantity, and limit before every send;
   both caught errors would have materially changed exposure.
2. News abstention should be governed symmetrically; suppressing the downside
   rule while holding discretionary calls is thesis-dependent selection.
3. Real, challenge, and published-pick variants of the same contract require
   deduplication and one aggregate delta ledger.
4. Same-day theta warnings need a time-stamped exit rule, not only qualitative
   advice after decay has accelerated.
5. A trade without a narrated entry cannot support return or expectancy claims.

## Contradictions and Process Risks

- The challenge ticket was nearly submitted as puts and later used the wrong
  strike before correction.
- A formal downside setup was skipped for news while discretionary calls
  remained exposed to that news.
- Challenge, real, and pick calls used the same expiration/strike and nearby
  entries but were discussed as separate outcomes.
- A second put was treated as open even though its entry premium was absent.
- Opposing calls and puts remained open with no aggregate loss ceiling.

## Falsifiable Replay Hypotheses

1. Enforce a five-field order-ticket checksum before submission.
2. Apply a symmetric news-window rule to formal and discretionary positions.
3. Deduplicate all same-contract call variants in performance statistics.
4. Test a fixed Wednesday exit for Friday-expiring options.
5. Reject any trade from expectancy calculations when entry evidence is absent.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, quantity for real calls or puts,
second-put entry, challenge/call exits, final pick EOD fill, aggregate
delta/gamma, synchronized bars, executable option paths, MFE/MAE, spreads,
slippage, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, news-window,
order-entry, or aggregate-risk change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
