# McLeod Alpha Research Report: 2025-08-22 Trading Room — Post 41368

## Executive Assessment

August 22 was dominated by Powell's Jackson Hole speech. The formal upside OMG
bought August 29 638 calls at `5.42` and exited around `5.76`. A separate
14-contract 320 challenge used the same contract, entered `5.49`, and exited
`5.76` after 47 seconds; the presenter reported `368` dollars after commission.

Calls inherited from August 21 were removed by a trailing stop, but no exit
premium was stated. A co-presenter also announced an unpriced short before
Powell and never reported its cover. After the speech produced an approximately
six-point SPY surge, August 29 643 calls entered `5.44` and filled `5.65`.
A same-day 645-call challenge then scalped `1.52` to `1.73` on 50 contracts,
with reported net P&L of `1,040` dollars. Three additional real-money
same-day 639-call scalps were disclosed retrospectively; only the first was
fully priced (`2.23` to `2.45`), while the later two lacked complete exits.

## Source Lineage and Evidence Quality

- Post `41368`; Vimeo `1112373524` (`TR Aug 22`), duration `01:13:27`.
- Complete authorized VTT: 1,595 cues, `00:00:00-01:13:13`.
- Player remained paused at `00:00`; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Powell's scheduled speech was the controlling event.
- OMG boundaries were approximately `637.58` upside and `636.86` downside.
- SPY broke upward early, consolidated, pulled back before the speech, then
  jumped roughly six points when the policy language was released.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:10:42-00:16:00 | Prior-day calls were disclosed and later removed by a trailing stop without a price. | Closed status is supported; realized result is unavailable. |
| 00:12:57-00:14:53 | OMG 638 calls entered `5.42` and sold around `5.76`. | Completed presenter trade. |
| 00:14:02-00:14:53 | Challenge 638 calls entered `5.49`, sold `5.76`; later timed at 47 seconds and reported `368` dollars net. | Separate mandate despite the shared contract. |
| 00:34:21-00:35:26 | Co-presenter announced a short but gave no contract, premium, or terminal cover. | Unresolved and not scorable. |
| 00:37:36-00:40:18 | Powell headlines produced an approximately six-point surge. | Event regime made ordinary technical entries unusually hazardous. |
| 00:46:27-00:47:54 | August 29 643 calls entered `5.44`, target `5.65` filled. | Completed post-news call. |
| 00:52:04-00:53:57 | Fifty same-day 645 calls entered `1.52`, sold `1.73`; reported `1,040` dollars net. | Completed challenge scalp. |
| 01:08:41-01:09:25 | Three unannounced real-money 639-call scalps were disclosed; only the first had both prices. | Preserve partial ledger quality. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250822-P41368-T01 | August 29 638 calls; upside OMG | `5.42` | approximately `5.76`; completed |
| DTS-20250822-P41368-T02 | August 29 638 calls; 320 challenge, 14 contracts | `5.49` | `5.76`; reported `368` dollars net |
| DTS-20250822-P41368-T03 | August 29 637 calls; inherited from August 21 | prior source | trailing-stop exit; premium unavailable |
| DTS-20250822-P41368-T04 | Co-presenter short | terms unavailable | unresolved |
| DTS-20250822-P41368-T05 | August 29 643 calls; post-Powell | `5.44` | `5.65`; completed |
| DTS-20250822-P41368-T06 | August 22 645 calls; challenge, 50 contracts | `1.52` | `1.73`; reported `1,040` dollars net |
| DTS-20250822-P41368-T07 | August 22 639 calls; real-money scalp 1, five contracts | `2.23` | `2.45`; completed |
| DTS-20250822-P41368-T08 | August 22 639 calls; real-money scalp 2, five contracts | `2.57` | completed; exit premium unavailable |
| DTS-20250822-P41368-T09 | August 22 639 calls; real-money scalp 3, five contracts | approximately `2.48` | completed; exit premium unavailable |

Participant trades and the still-open published pick are not converted into
presenter executions.

## Entry and Exit Lessons

1. Shared strikes require strategy/account tags to avoid double-counting.
2. A stop-exit statement supports closure, not an invented fill price.
3. Event headlines can create discontinuous moves that overwhelm normal
   technical assumptions and widen spreads.
4. Post-event scalps can be classified only from explicit entries and exits.
5. Retrospective real-money demonstrations need the same fill completeness as
   announced trades.

## Contradictions and Process Risks

- The room warned that trading Powell was roulette, then entered several
  post-headline calls.
- The inherited call and co-presenter short lacked executable reconciliation.
- The challenge series mixed simulated/educational and real-money examples.
- Two of three disclosed micro-scalps omitted terminal premiums.
- Advice to hold puts through the event was not tied to a presenter fill.

## Falsifiable Replay Hypotheses

1. Strategy-tagged orders eliminate same-contract double-counting.
2. A no-entry window around scheduled central-bank headlines reduces tail risk.
3. Post-event retracement confirmation improves fill quality over impulse entry.
4. Fixed-target scalps outperform discretionary holds in high-spread regimes.
5. Complete retrospective ledgers materially change reported micro-scalp P&L.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, inherited-call exit premium,
co-presenter short terms, two micro-scalp exit premiums, published-pick
terminal state, independent P&L reconciliation, executable option paths,
aggregate exposure, synchronized bars, Greeks, MFE/MAE, spreads, slippage, or
complete fees is available.

## Explicit Non-Changes

No live event-window, OMG, target, trailing-stop, sizing, challenge,
micro-scalp, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
