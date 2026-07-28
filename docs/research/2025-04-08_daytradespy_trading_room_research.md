# McLeod Alpha Research Report: 2025-04-08 Trading Room

## Executive Assessment

Authorized browser captions cover 486 distinct cues from 00:00:00 through
01:13:02 of a 01:13:13 asset. The source initially withheld an OMG trade while
price remained inside its lines, then reported an April 11 525-call OMG trade
after an upside break. It stated a captioned 9.12 entry value, a 9.67 target,
and a later sale at a captioned 10.05 value.

The source also discussed exiting 546 calls ahead of Friday expiry. Contract
symbols, quantity, order identity, fills, costs, and an independent market path
are unavailable for both positions.

## Source Lineage and Evidence Quality

- Recording: Day Trade SPY post `39375`, "Trading Room Video Recording - April
  8, 2025."
- Source: authenticated Vimeo asset `1073719420`, English auto-generated
  captions collected in the authorized browser transcript panel.
- Transcript coverage: 99%, 00:00:00 through 01:13:02; final browser-visible
  cue is 11 seconds before asset duration.
- Visual review, speaker attribution, underlying bars, option marks, broker
  executions, and canonical ledger mapping: unavailable.
- Evidence tier: C, `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Recording time | Evidence | Research interpretation |
| --- | --- | --- |
| 00:05:23 | Source framed a 522-area high, 523-area resistance, 504.67 pivot, and 529.87 first resistance. | Structural context only; level interactions need bar reconstruction. |
| 00:06:51-00:07:16 | Source discussed exiting 546 calls before Friday expiry and described elevated option volatility. | Position and risk commentary are source-only; no fill is identified. |
| 00:20:52 | Source stated there was no OMG trade while price was inside the lines. | Candidate admission filter, not a validated rule. |
| 00:38:20-00:39:21 | Source identified April 11 525 calls, a 9.12 captioned entry value, 9.67 target, and 524.27 estimated underlying target. | Source order intent only until contract and broker evidence are reconciled. |
| 00:43:53-00:44:15 | Source reported selling at a captioned 10.05 after the stated 9.67 target. | Reported outcome only; target and sale remain distinct source events. |

## Presenter-Reported Trades

| Source trade | Instrument and stated setup | Reported entry | Reported exit/outcome | Reconciliation status |
| --- | --- | --- | --- | --- |
| DTS-20250408-T01 | 546 calls held near Friday expiry | Unknown | Exit discussed, not reported | No expiry, size, entry, or fill identity. |
| DTS-20250408-T02 | April 11 525 calls after stated OMG upside break | 9.12 captioned source value | 9.67 target; later sale at 10.05 captioned source value | No broker/order lineage or independent marks. |

## Ledger Reconciliation

No canonical ledger mapping, broker executions, underlying bars, option marks,
or excursion data was available. The 546-call position cannot be resolved to a
specific contract or outcome. The April 11 525-call values are source captions,
not verified fills; the stated target and later reported sale are preserved as
separate events. There are zero confirmed McLeod Alpha matches.

## Recurring and Contradictory Evidence

- Recurring: source tied OMG admission to a level condition, then referenced
  breakout, nearby resistance, and room to the next pivot.
- Recurring: high implied volatility and uncertainty around option liquidity
  constrained trade participation and expiry-risk management.
- Tension: an earlier no-trade condition later transitioned to a reported OMG
  trade; the transition requires deterministic close/break labels.
- Limitation: participant profits were not merged with presenter execution.

## Candidate Hypotheses

1. Test an OMG inside-lines no-trade filter against deterministic breakout and
   close conditions, executable marks, costs, and a baseline replay.
2. Test whether structural room to the next pivot/resistance improves the
   cost-adjusted outcome of accepted upside breaks.
3. Test predeclared option-target lifecycle quality using actual submitted
   orders, fills, MFE/MAE, and missed-opportunity cost.

## Instrumentation Gaps

- Visual chart and order review, speaker attribution, contract symbols, and
  order identifiers.
- Timestamped underlying bars, executable option bid/ask/mark data, MFE/MAE,
  broker fills, fees, and canonical ledger mapping.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, averaging, or risk-policy change
is authorized from this recording.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.