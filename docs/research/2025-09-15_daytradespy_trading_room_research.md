# McLeod Alpha Research Report: 2025-09-15 Trading Room — Post 41599

## Executive Assessment

September 15 was a strong upside session in which the presenter reported three
completed call trades. The formal September 19 659-call OMG entered at `3.80`
after five-minute and one-minute confirmation and sold at its `4.02` target.
Two later September 19 660-call scalps closed `3.64` to `3.74` and `3.52` to
`3.64`.

The presenter also banked an incompletely specified position carried from
Friday, and said the published pick completed, but the source does not provide
enough terms to calculate either result. A downside reversal and a separate
runaway call idea were not filled. The final call scalp exposed simulator
ambiguity: the delayed order appeared to execute after the presenter thought it
had not, yet the source subsequently stated both entry and exit prices.

## Source Lineage and Evidence Quality

- Post `41599`; Vimeo `1118825543` (`9-15 TR`), duration `01:10:09`.
- Complete authorized VTT: 1,159 cues, `00:00:00-01:10:06`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- SPY made a strong bullish move and approached the upper OMG boundary near
  `659.71`.
- The presenter required a five-minute close followed by one-minute
  confirmation before the formal upside OMG entry.
- Momentum repeatedly ran away from queued orders, creating chase pressure.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:12:39-00:12:59 | Presenter banked the remaining portion of a Friday trade. | Completed carry, terms unavailable. |
| 00:15:47-00:15:53 | Sep. 19 659 calls filled `3.80` after confirmation. | Formal upside OMG entry. |
| 00:20:06-00:20:13 | Calls sold `4.02`; target was `4.01/4.02`. | Completed 22-cent OMG. |
| 00:20:20 | Published pick was reported sold. | Completed modeled pick; terms unavailable. |
| 00:24:09-00:24:20 | Downside reversal moved without a source fill. | `NO_TRADE`. |
| 00:27:43-00:27:54 | Presenter killed a call order after price ran away. | Correct non-chase decision. |
| 00:38:38-00:39:54 | Sep. 19 660 calls entered `3.64`, sold `3.74`. | Completed 10-cent scalp. |
| 01:04:40-01:06:11 | Delayed Sep. 19 660-call fill at `3.52`, sold `3.64`. | Completed 12-cent scalp with order-state risk. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250915-P41599-T01 | Friday carry position | terms unavailable | banked early; result not computable |
| DTS-20250915-P41599-T02 | Sep. 19 659 calls; upside OMG | `3.80` | `4.02` |
| DTS-20250915-P41599-T03 | Published pick | terms unavailable | reported sold; result not computable |
| DTS-20250915-P41599-T04 | Downside reversal | no fill | `NO_TRADE`; move was missed |
| DTS-20250915-P41599-T05 | Runaway call scalp | no fill | `NO_TRADE`; order killed |
| DTS-20250915-P41599-T06 | Sep. 19 660 calls; scalp | `3.64` | `3.74` |
| DTS-20250915-P41599-T07 | Sep. 19 660 calls; delayed-order scalp | `3.52` | `3.64` |

## Entry and Exit Lessons

1. The two-stage OMG confirmation gate produced a fully specified trade.
2. Refusing to chase a missed entry preserved entry discipline.
3. A delayed simulator acknowledgement can create unintended exposure.
4. Published-pick and carry results require terms before inclusion in return
   statistics.
5. Repeated same-direction scalps should be evaluated independently, not
   bundled into the formal OMG result.

## Contradictions and Process Risks

- The final `3.52` fill occurred through ambiguous order behavior rather than a
  cleanly acknowledged entry.
- The carry and published-pick outcomes were described as gains without
  complete entries, exits, sizes, or independent reconciliation.
- A favorable trending session does not validate execution quality.

## Falsifiable Replay Hypotheses

1. Five-minute plus one-minute confirmation improves OMG precision.
2. A maximum chase distance improves realized entry quality.
3. Order acknowledgements prevent duplicate or unintended simulator exposure.
4. A one-OMG-plus-limited-scalps cap reduces overtrading after an early win.
5. Ledger-complete trade terms materially lower the apparent success rate.

## Ledger and Instrumentation Gaps

No full visual review, carry or published-pick terms, broker/simulator ledger,
independent P&L, sizes, executable option paths, synchronized bars, Greeks,
MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, confirmation, chase, repeat-trade, sizing, direction, or risk
policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
