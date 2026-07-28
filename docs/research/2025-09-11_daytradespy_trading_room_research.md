# McLeod Alpha Research Report: 2025-09-11 Trading Room — Post 41576

## Executive Assessment

September 11 produced a completed upside OMG. September 19 655 calls entered
`4.55`, worked near a `4.82` target, and were sold at `4.85`. The published pick
was also reported successful without reconstructable terms.

The presenter closed a carried call position at `5.20`, but described its entry
as `4.55`, conflicting with the September 10 recording's `4.86` entry for its
open 654 calls. This may be a different carried position, so it remains a
possible rather than confirmed cross-day match. A later September 19 656-call
trade entered `4.39` and appears to have hit its working `4.69` limit at the
terminal cue; the source did not restate the fill price.

## Source Lineage and Evidence Quality

- Post `41576`; Vimeo `1117878454` (`9-11 TR`), duration `01:23:15`.
- Complete authorized VTT: 1,390 cues, `00:00:02-01:14:27`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Price remained in a broad multiday range before breaking upward.
- OMG boundaries were `654.70` upside and `653.31` downside.
- The upside close was followed by one-minute confirmation and continued new
  highs.
- The presenter expected Friday profit-taking and preferred not to hold the
  final call overnight.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:28:27-00:30:13 | Published pick moved through its target and was reported complete. | Source-reported/model result; terms absent. |
| 00:31:32-00:34:59 | Upside OMG confirmed; Sep. 19 655 calls filled `4.55`, target `4.82`. | Position opened. |
| 00:32:34-00:35:10 | Carried calls closed `5.20`; source described prior entry `4.55`. | Completed, but cross-day lineage conflicts with Sep. 10. |
| 00:39:48-00:40:29 | OMG calls sold at `4.85`; source described partial then remainder exit. | Completed source-reported OMG winner. |
| 00:41:27-00:47:25 | A further upside scalp was described but missed by the presenter. | Analysis/missed trade, not presenter fill. |
| 01:04:05-01:05:18 | Sep. 19 656 calls filled `4.39`, working target `4.69`. | Late call trade opened. |
| 01:10:41-01:12:17 | Entry/target repeated; presenter then said he was taken out. | Likely completed via `4.69` limit; exact exit not restated. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250911-P41576-T01 | Published upside pick | terms unavailable | reported successful |
| DTS-20250911-P41576-T02 | Carried call position | next-day recap `4.55`; prior-day possible match `4.86` | `5.20`; lineage unresolved |
| DTS-20250911-P41576-T03 | Sep. 19 655 calls; upside OMG | `4.55` | `4.85` |
| DTS-20250911-P41576-T04 | Further upside scalp | no fill | `NO_TRADE`; presenter missed entry |
| DTS-20250911-P41576-T05 | Sep. 19 656 calls | `4.39` | reported taken out via working `4.69` limit; price not restated |

## Entry and Exit Lessons

1. Cross-day positions need stable identifiers, not narrative matching.
2. Waiting for a five-minute close and one-minute test produced a clean OMG.
3. Missing a trade after two wins is preferable to chasing it.
4. Working-limit inference must remain distinct from an explicit fill.
5. Late-session positions need a terminal ledger before sign-off.

## Contradictions and Process Risks

- The carried call's stated `4.55` entry conflicts with the prior recording's
  open `4.86` call.
- The OMG target was first stated `4.82` and the reported exit was `4.85`;
  broker evidence is absent.
- The last call's `4.69` exit is inferred from the active limit plus “taken
  out,” not explicitly restated.

## Falsifiable Replay Hypotheses

1. Two-timeframe confirmation improves upside OMG entries.
2. A stable cross-day position ID eliminates false trade reconciliation.
3. No-chase rules improve outcomes after missed breakouts.
4. Terminal fill capture reduces inferred-exit uncertainty.
5. Friday overnight exclusions improve late-call tail risk.

## Ledger and Instrumentation Gaps

No full visual review, pick fills, cross-day position identifier, broker orders,
exact carried-call lineage, explicit final-call exit price, independent P&L,
sizes, executable option paths, synchronized bars, Greeks, MFE/MAE, spreads,
slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, cross-day reconciliation, late-entry, overnight, sizing,
direction, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
