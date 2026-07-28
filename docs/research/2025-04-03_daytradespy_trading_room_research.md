# McLeod Alpha Research Report: 2025-04-03 Trading Room

## Executive Assessment

Authorized browser captions cover 490 cues from 00:00:00 through 01:11:50. The
source reported an April 11 547-call OMG fill at 9.29 with a 9.85 target, but
later said the OMG position was still held. A participant separately reported a
prior-day 565-put result. The recording’s strongest reusable observation is the
distinction between a clean breakout that retests and holds and a false break
that reverses. No source outcome is independently verified.

## Source Lineage and Evidence Quality

- Recording: Day Trade SPY post `39274`, "Trading Room Video Recording - April
  3, 2025."
- Source: authenticated Vimeo asset `1073227272`, English auto-generated
  captions collected in the authorized browser transcript panel.
- Transcript coverage: browser-visible cues through 01:11:50; remaining player
  content is uncued or unavailable.
- Visual review, speaker attribution, underlying bars, option marks, broker
  executions, and canonical ledger mapping: unavailable.
- Evidence tier: C, `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Recording time | Evidence | Research interpretation |
| --- | --- | --- |
| 00:09:47-00:17:43 | Source waited for retracement and OMG close, then reported April 11 547 calls at 9.29 with a 9.85 target. | Source position and target only; no confirmed target fill. |
| 00:23:14-00:23:45 | Participant reported prior-day 565 puts from 9.31 to 20.00 and $12,230 profit. | Participant claim about another session; no reconciliation. |
| 00:40:48-00:46:48 | Source said the OMG position remained held while price tested or broke support. | Conflicts with treating the earlier target as an outcome. |
| 01:08:39-01:10:30 | Source described false breakouts and required a return test and hold of the broken level for a clean break. | Candidate accepted-breakout definition requiring deterministic replay. |

## Presenter-Reported Trades

| Source trade | Instrument and stated setup | Reported entry | Reported exit/outcome | Reconciliation status |
| --- | --- | --- | --- | --- |
| DTS-20250403-T01 | April 11 547 calls; OMG-labelled | 9.29 | 9.85 target only; later said still held | No confirmed exit or broker fill. |
| DTS-20250403-T02 | Prior-day 565 puts; participant report | 9.31 | 20.00; $12,230 stated profit | Participant source claim only. |

## Ledger Reconciliation

No canonical ledger mapping, broker executions, underlying bars, option marks,
or excursion data was available. The stated call target is not treated as a
sale because later source language retains the position. The participant put
claim has no speaker, contract, or broker identity. There are zero confirmed
McLeod Alpha matches.

## Recurring and Contradictory Evidence

- Recurring: source required retracement, close, test, and hold rather than a
  first penetration.
- Recurring: support, resistance, 10-MA, 20-MA, and retracement references
  framed the session state.
- Contradiction: a stated call target precedes later language that the position
  remained held.
- Ambiguity: the 546-call discussion and the 547-call fill cannot be linked
  without contract and order identifiers.

## Candidate Hypotheses

1. Test close-plus-retest-and-hold breakout labels against first penetrations
   with timestamped bars and executable option paths.
2. Test OMG entries only after deterministic close, resistance, and pullback
   labels are available.
3. Compare predeclared target exits with held-position management using order
   histories, MFE/MAE, and actual fills.

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