# McLeod Alpha Research Report: 2025-09-08 Trading Room — Post 41538

## Executive Assessment

September 8 was a narrow, choppy session with no early formal OMG trade. A
published pick was reported complete, but its source terms were not stated. The
presenter bought September 12 648 calls at `4.16`, held them for nearly an hour,
and had part of the position removed by an unpriced trailing stop. The remaining
exit is not stated clearly enough to assign a premium.

At `10:42` market time, after the first upside OMG close, the presenter bought
September 12 649 calls at `3.70` with a `3.90` target and called it an
“unofficial OMG.” The recording ended with the position still open. The session
therefore does not support a fully closed winning-day classification.

## Source Lineage and Evidence Quality

- Post `41538`; Vimeo `1116845470` (`9-8 TR`), duration `01:26:31`.
- Complete authorized VTT: 1,308 cues, `00:00:00-01:23:49`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Futures rebounded after another profit-taking Friday.
- OMG boundaries were approximately `648.93` upside and an unstated lower
  boundary.
- Price stayed range-bound for most of the recording and did not close above
  the upside OMG until roughly `10:40`.
- The presenter repeatedly emphasized weak follow-through and failed tests.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:09:31-00:14:43 | Published pick monitored and reported taken out; terms absent. | Completed source claim, not reconstructable. |
| 00:21:30-01:17:19 | Sep. 12 648 calls entered `4.16`, initial target `4.38`; part hit an unpriced trailing stop and the remainder's exact exit was unclear. | Outcome and P&L unresolved. |
| 00:23:16 | Presenter explicitly declined the `360` trade. | `NO_TRADE`. |
| 00:38:01 | No formal OMG trade during the 10:00 hour. | Valid abstention in chop. |
| 01:10:47-01:14:40 | Trailing stop removed part of the 648-call position just before a rebound. | Stop-placement counterfactual. |
| 01:18:11-01:20:43 | First upside OMG close; Sep. 12 649 calls bought `3.70`, target `3.90`. | Late unofficial OMG opened. |
| 01:21:07-terminal | Presenter expected a near-term close, but no fill was captured. | Terminal unresolved position. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250908-P41538-T01 | Published pick | terms unavailable | reported taken out successfully |
| DTS-20250908-P41538-T02 | Sep. 12 648 calls | `4.16` | partial trailing-stop exit unpriced; remainder unresolved |
| DTS-20250908-P41538-T03 | `360` challenge | no fill | `NO_TRADE` |
| DTS-20250908-P41538-T04 | Sep. 12 649 calls; late unofficial upside OMG | `3.70` | unresolved; target `3.90` |

## Entry and Exit Lessons

1. Range-bound days reward abstention more reliably than anticipatory entries.
2. A trailing stop needs a stated distance and fill to be replayable.
3. Partial exits cannot be converted into trade P&L without quantity and price.
4. Late entries need terminal-ledger capture when the recording ends.
5. “Almost hit target” is not an exit.

## Contradictions and Process Risks

- The 648-call entry preceded formal OMG confirmation and remained open through
  extended chop.
- The presenter criticized the trailing stop after it executed, but its
  placement and fill were never stated.
- A rebound and proximity to target do not establish the remainder's exit.
- The final trade was described optimistically but remained open on source.

## Falsifiable Replay Hypotheses

1. Waiting for the actual OMG close outperforms anticipatory range entries.
2. Volatility-scaled trailing stops outperform unspecified manual placement.
3. A maximum holding-time rule reduces capital lockup on choppy days.
4. Terminal ledger enforcement prevents open late trades from entering win
   statistics.

## Ledger and Instrumentation Gaps

No full visual review, published-pick terms, challenge order, trailing-stop
distance/fill/quantity, remainder exit, terminal 649-call fill, broker ledger,
independent P&L, executable option path, synchronized bars, Greeks, MFE/MAE,
spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, trailing-stop, holding-time, sizing, direction, or risk-policy
change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
