# McLeod Alpha Research Report: 2025-07-16 Trading Room — Post 40943

## Executive Assessment

July 16 contained three completed narrated trades and one unresolved
late-session put. Twenty-six July 25 624 calls in the challenge filled at
`2.58`; because the simulator would not accept the exit, the presenter modeled
a `2.75` sale after the contract had traded as high as `2.85`. The formal
downside OMG used July 25 623 puts from `4.65` to `4.94`. A discretionary
follow-on 623-put trade ran from `5.15` to `5.43`.

A final July 25 622-put trade entered at `4.65` with an initial `4.85` target
but was adverse and open at the terminal cue. The room also acknowledged that a
prior pick had been reported under an incorrect 40% stop rather than the
published end-of-day rule. The correction was candid, but it exposes mutable
outcome policy and a material reporting-control weakness.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40943`, published July 16, 2025.
- Authenticated Vimeo asset `1101967514`, title `7-16 TR`, duration
  `01:10:59`.
- Complete authorized English auto-generated VTT: 1,332 cues span
  `00:00:00-01:10:57`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- PPI, firmer CPI, bank earnings, several Fed speakers, and the next day's
  retail-sales data framed an event-heavy morning.
- Approximate OMG boundaries were `623.93` upside and `623.22` downside.
- SPY failed early upside attempts, broke the pivot and prior close, filled the
  open gap, and later attempted a recovery from the `622.20` area.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:11:03-00:19:20 | Twenty-six July 25 624 challenge calls filled at `2.58`; a malfunctioning simulator led to a modeled `2.75` sale and claimed `$432` net. | The economic result is hypothetical without an executable exit event. |
| 00:21:22-00:23:29 | Presenters found the prior pick should use an EOD rule; a previously reported 40% stop was called a mistake. | Outcome governance was mutable and the historical record requires correction. |
| 00:23:33-00:28:47 | July 25 623 OMG puts entered at `4.65`, target `4.93`, and filled at `4.94`. | A clearly narrated formal trade captured the breakdown. |
| 00:28:14-00:28:23 | A separate trade was said to mirror the OMG. | Signal duplication must be reconciled before counting independent evidence. |
| 00:37:48-00:46:22 | Discretionary July 25 623 puts entered `5.15`, target `5.35`, and exited `5.43`. | A continuation entry succeeded but relied on a very short move near support. |
| 00:57:33-01:03:21 | Pick holders were told the reportable position ended at EOD while a personal holder could continue overnight. | Reporting and discretionary ledgers again diverged. |
| 01:04:30-01:10:26 | July 25 622 puts entered at `4.65`, initial target `4.85`; an upside break made it adverse and unresolved. | The presenter explicitly treated the losing position as a “sacrificial trade,” not a defined-risk exit. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250716-P40943-T01 | 26 July 25 624 calls; challenge | `2.58` | modeled `2.75`; simulator exit unavailable |
| DTS-20250716-P40943-T02 | July 25 623 puts; formal downside OMG | `4.65` | `4.94`; target `4.93` |
| DTS-20250716-P40943-T03 | July 25 623 puts; discretionary continuation | `5.15` | `5.43`; target `5.35` |
| DTS-20250716-P40943-T04 | July 25 622 puts; late discretionary trade | `4.65` | open/adverse; initial target `4.85` |

## Entry and Exit Lessons

1. A modeled fill after a simulator failure must be labeled hypothetical and
   excluded from realized-P&L evidence.
2. Published outcome rules must be versioned and immutable for each signal;
   corrections should never overwrite the original event.
3. OMG and a mirroring discretionary trade are correlated exposure, not two
   independent confirmations.
4. Continuation entries near known support need explicit invalidation before
   entry despite a tight upside premium target.
5. A losing trade cannot be justified as sacrificial; it needs a quantified
   loss limit and terminal resolution.

## Contradictions and Process Risks

- The challenge exit was reconstructed at `2.75` because the simulator failed,
  even though the contract had printed `2.85`.
- A prior pick was first reported at a 40% loss, then reassigned to an EOD rule.
- The formal OMG and a separate trade mirrored the same downside move.
- Reportable EOD treatment and personal overnight holding were both advocated.
- The late 622 puts were held through a contrary upside break without a stated
  maximum loss.

## Falsifiable Replay Hypotheses

1. Exclude modeled exits and compare results using executable fills only.
2. Freeze pick outcome rules at publication and maintain correction events.
3. Deduplicate mirrored OMG and discretionary exposure.
4. Apply a support-aware invalidation to downside continuation entries.
5. Compare a fixed stop with “sacrificial” holding on the late 622 puts.

## Ledger and Instrumentation Gaps

No full visual review, functioning simulator exit, broker orders, quantities
for discretionary trades, exact mirrored-trade premium, final pick EOD fill,
late-put resolution, aggregate exposure, synchronized bars, executable option
paths, MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, reporting,
overnight-hold, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
