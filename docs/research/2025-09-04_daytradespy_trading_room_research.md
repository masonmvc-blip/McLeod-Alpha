# McLeod Alpha Research Report: 2025-09-04 Trading Room — Post 41486

## Executive Assessment

September 4 began with upside momentum, then reversed after services data
before recovering. The `360` challenge bought 15 September 12 645 calls around
`4.90-4.92` and sold `5.20`; the final recap reported `440` dollars net after
commission. A separate real-money 645-call trade ran `4.94-5.29`.

The formal upside OMG entered September 12 645 calls at `5.13` with a `5.44`
target and remained unresolved at the terminal cue. Another 646-call position
entered `4.66`, added an equal quantity at `4.16`, averaged `4.41`, and sold
`4.55`. The presenter explicitly rejected fixed stop orders in favor of buying
time and waiting unless expiration was near—an important risk-policy
observation that requires independent drawdown testing.

## Source Lineage and Evidence Quality

- Post `41486`; Vimeo `1115934221` (`TR Sept 4`), duration `01:16:15`.
- Complete authorized VTT: 1,628 cues, `00:00:00-01:15:30`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- ADP, unemployment claims, S&P services PMI, and ISM services shaped the
  session.
- OMG boundaries were approximately `644.71` upside and `643.99` downside.
- Initial upside broke the OMG boundary, reversed toward `643.5`, then
  recovered above `645`.
- September 12 options were selected to tolerate intraday volatility.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:11:06-00:15:02 | `360` trade bought 15 Sep. 12 645 calls around `4.90-4.92`, sold `5.20`; final recap reported `440` dollars net. | Completed, with minor entry recap variance. |
| 00:12:43-00:15:39 | Separate real-money Sep. 12 645 calls entered `4.94`, sold `5.29`. | Completed source-reported winner. |
| 00:14:24-00:17:22 | Upside OMG confirmed; Sep. 12 645 calls entered `5.13`, target `5.44`. | Position opened. |
| 00:19:08-00:20:02 | Unannounced high-risk 645-call scalp entered `5.03`, sold `5.15`. | Completed discretionary scalp. |
| 00:24:47-01:10:40 | Sep. 12 646 calls entered `4.66`, equal add `4.16`, average `4.41`, sold `4.55`. | Completed scaled trade after material drawdown. |
| 00:57:59-00:58:08 | Sep. 12 644 puts were queued but not entered. | Explicit unfilled idea. |
| 01:03:35-01:04:41 | Presenter rejected fixed stops, preferring time and discretionary loss-taking near expiration. | Risk-governance concern. |
| 01:13:22-01:14:18 | OMG and signal remained open; source recap separately modeled a published pick `4.91-5.20`. | Terminal incompleteness. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250904-P41486-T01 | Sep. 12 645 calls; `360` challenge, 15 contracts | contemporaneous `4.92`, recap `4.90` | `5.20`; reported `440` dollars net |
| DTS-20250904-P41486-T02 | Sep. 12 645 calls; real money | `4.94` | `5.29` |
| DTS-20250904-P41486-T03 | Sep. 12 645 calls; upside OMG | `5.13` | unresolved; target `5.44` |
| DTS-20250904-P41486-T04 | Sep. 12 645 calls; unannounced high-risk scalp | `5.03` | `5.15` |
| DTS-20250904-P41486-T05 | Sep. 12 646 calls; scaled real-money trade | `4.66`, equal add `4.16`, average `4.41` | `4.55` |
| DTS-20250904-P41486-T06 | Sep. 12 644 puts; queued downside idea | no fill | `NO_TRADE` |
| DTS-20250904-P41486-T07 | Published Sep. 12 645-call pick; modeled | average `4.91` | modeled `5.20` |
| DTS-20250904-P41486-T08 | Signal-trigger position | terms unavailable | unresolved at terminal cue |

## Entry and Exit Lessons

1. Entry recaps must be checked against contemporaneous fills.
2. Overlapping challenge, personal, OMG, and signal positions create hidden
   directional concentration.
3. Averaging lowers break-even while increasing capital at risk.
4. Buying time does not replace a falsifiable invalidation rule.
5. Terminal open positions must remain unresolved until a later source or
   ledger supplies the exit.

## Contradictions and Process Risks

- The challenge entry was stated near `4.92` contemporaneously and `4.90` in
  recap.
- Several highly correlated call positions overlapped.
- The 646-call average required adding after a substantial decline.
- The presenter recommended having sell orders working but rejected fixed
  downside stops.
- The room declared a very good day while OMG and signal positions remained
  unresolved.

## Falsifiable Replay Hypotheses

1. Aggregate directional exposure limits reduce overlapping-call drawdowns.
2. Entry-fill reconciliation prevents favorable recap drift.
3. Fixed maximum-loss rules outperform discretionary time-based waiting.
4. Scaling only after renewed confirmation improves average-entry outcomes.
5. Terminal-ledger enforcement prevents open positions from entering win
   statistics.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, resolved challenge entry,
terminal OMG or signal fills, independent P&L, exact sizes for personal trades,
executable option paths, aggregate exposure, synchronized bars, Greeks,
MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, scaling, stop, overlapping-exposure, sizing, direction, or
risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
