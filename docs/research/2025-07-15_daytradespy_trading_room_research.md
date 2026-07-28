# McLeod Alpha Research Report: 2025-07-15 Trading Room — Post 40928

## Executive Assessment

July 15 produced a completed formal downside OMG and one completed
discretionary put trade, while an overnight call remained unresolved. The OMG
used July 18 626 puts at `2.89` and exited at `3.09`, one cent above its stated
`3.06` target. A later discretionary July 18 626-put trade entered at `3.20`,
initially targeted `3.40`, and was finally sold at `3.35` near the room close.

The presenter also carried July 18 631 calls from the prior close at `1.10`.
Those calls reached `1.63`, missed a `1.65` sell order, fell underwater, and
recovered only to about `1.15` before the terminal cue. This is direct evidence
that an unfilled target and refusal to take a smaller gain can convert a large
unrealized profit into an unresolved carry.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40928`, published July 15, 2025.
- Authenticated Vimeo asset `1101618453`, title `7-15 TR`, duration
  `01:08:12`.
- Complete authorized English auto-generated VTT: 1,038 cues span
  `00:00:00-01:08:03`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- CPI, semiconductor strength, Fed commentary, and the start of bank-earnings
  season framed a positive longer-term bias after an opening record high.
- Approximate OMG boundaries were `627.97` upside and `626.37` downside.
- SPY sold through the lower boundary, then spent much of the room oscillating
  without follow-through around `625-626`.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:05:00-00:06:51 | July 18 631 calls carried from the prior close at `1.10` were nearly 50% higher; a `1.65` sell was sought. | A profitable overnight carry was managed with a single optimistic limit. |
| 00:21:03-00:25:22 | A downside close activated July 18 626 OMG puts at `2.89`; they sold at `3.09` against a `3.06` target. | Formal signal and exit were clearly narrated, but no immutable order ledger is available. |
| 00:35:49-00:37:13 | Discretionary July 18 626 puts entered at `3.20`; initial target `3.40`. | Entry followed an already extended decline and lacked an explicit maximum loss. |
| 00:40:35-00:40:49 | The overnight calls were underwater after having been almost 50% higher; the presenter chose to wait for renewed profit. | Anchoring to the missed high replaced a defined exit rule. |
| 00:45:45-00:45:58 | Pick repair was deferred until the market was demonstrably trending back in its direction. | Repair discipline was better than averaging into ongoing weakness, but the underlying pick was not reconciled. |
| 00:58:06-00:58:32 | The 631 calls had reached `1.63`, missed the `1.65` order by two cents, and were back near `1.15`. | A 48% unrealized gain contracted to roughly 5% while the position remained open. |
| 01:06:33-01:07:52 | The put target was reduced; bid was `3.25`, and the trade sold at `3.35`, after which `3.41` printed. | Adaptive exit preserved a gain, though the adjustment was discretionary and late. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250715-P40928-T01 | July 18 631 calls; prior-close discretionary carry | `1.10` | open; high `1.63`, missed `1.65` sell, later about `1.15` |
| DTS-20250715-P40928-T02 | July 18 626 puts; formal downside OMG | `2.89` | `3.09`; stated target `3.06` |
| DTS-20250715-P40928-T03 | July 18 626 puts; discretionary trade | `3.20` | `3.35`; initial target `3.40` |

## Entry and Exit Lessons

1. A limit two cents above the observed high is not an exit; track the actual
   fill and define what happens after a near miss.
2. Formal entries need immutable order events even when narration supplies
   apparently exact premiums and times.
3. Late-trend discretionary entries require an initial maximum loss and time
   stop, not only a profit target.
4. Reducing a target can be rational when follow-through disappears, but the
   adjustment rule must be declared and replayable.
5. A repair should not begin until objective recovery criteria are satisfied,
   and it must remain linked to the original position ledger.

## Contradictions and Process Risks

- The overnight call was celebrated near a 50% gain, but no fill occurred and
  it later went underwater.
- The 626-put discretionary trade had an initial `3.40` target, was discussed
  near `3.32`, sold at `3.35`, and immediately printed around `3.41`.
- The presenters expressed confidence in both outstanding calls and puts during
  a low-conviction range, obscuring aggregate directional exposure.
- Pick-repair discussion lacked the original pick's contract, fill, size, and
  current loss.

## Falsifiable Replay Hypotheses

1. Compare a near-miss fallback exit with leaving the original limit unchanged.
2. Reconcile the OMG narration against immutable simulator order events.
3. Test a fixed loss/time stop for post-breakdown discretionary put entries.
4. Replay rule-based versus discretionary target reductions in stalled trends.
5. Track simultaneous calls, puts, and repairs under one exposure ledger.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator order events, quantities for the
overnight or discretionary trades, definitive pick ledger, aggregate delta,
synchronized bars, executable option paths, MFE/MAE, spreads, slippage, or
complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, overnight-hold,
repair, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
