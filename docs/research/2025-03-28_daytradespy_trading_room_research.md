# McLeod Alpha Research Report: 2025-03-28 Trading Room

## Executive Assessment

Authorized auto-captions cover 1,513 cues from 00:00:00 through 01:11:02 of a
01:11:25 recording. The source includes multiple named and unnamed participant
claims, including April 4 put scalps and a historical 575-call loss. Captions
lack speaker attribution and contain unresolved strike and arithmetic conflicts.
No source claim is treated as verified execution or realized performance.

## Source Lineage and Evidence Quality

- Recording: Day Trade SPY post `39133`, "Trading Room Video Recording - March
  28, 2025."
- Source: authenticated Vimeo asset `1071127604`, signed English auto-generated
  caption track with 1,513 cues.
- Transcript coverage: 99.5%, 00:00:00 through 01:11:02; final 23 seconds are
  uncued and unknown.
- Visual review, speaker attribution, broker executions, option marks,
  underlying bars, and canonical ledger mapping: unavailable.
- Evidence tier: C, `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Recording time | Evidence | Research interpretation |
| --- | --- | --- |
| 00:09:43-00:10:14 | Speaker stated holding 23 calls at caption-rendered 5.11. | Existing position; strike, expiry, exact entry, and outcome unknown. |
| 00:23:22-00:25:35 | Participant reported April 4 566 puts from 6.82 to 7.07. | Source-reported participant scalp; size and attribution unavailable. |
| 00:32:12-00:35:37 | Participant reported 563 puts at 6.00 and a 6.16 sale after three minutes; nearby captions cite 562 and 564 strikes. | Unlinked order sequence; strike identity is unresolved. |
| 00:45:24-00:46:52 | Named John reported April 4 563 puts from 6.51 to 6.79. | Source-only claim; stated 8 cents conflicts with price arithmetic. |
| 00:53:31-00:54:10 | Speaker described prior Wednesday 575 calls from 7.10 to 5.90 after failure to rebound through stated SPY 574. | Historical loss claim, not a March 28 entry. |

## Source-Reported Trades

| Source trade | Instrument and stated setup | Reported entry | Reported exit/outcome | Reconciliation status |
| --- | --- | --- | --- | --- |
| DTS-20250328-T01 | April 4 566 puts; participant claim | 6.82 | 7.07 | Size and speaker attribution unavailable. |
| DTS-20250328-T02 | Put order sequence with 563/562/564 strike conflict | 6.00 on captioned 563 puts | 6.16 stated sale after three minutes | Captions do not establish one reconciled contract. |
| DTS-20250328-T03 | April 4 563 puts; attributed in dialogue to John | 6.51 | 6.79 | Stated 8 cents and 4.3% conflict with 0.28 price change. |
| DTS-20250328-T04 | Historical 575 calls; prior Wednesday | 7.10 | 5.90 | Historical source loss claim; size unavailable. |

## Ledger Reconciliation

No canonical ledger mapping, broker executions, option marks, underlying bars,
or excursion data was available. The 563/562/564 put references are not merged.
The 6.51-to-6.79 claim is retained alongside its internally inconsistent stated
8-cent and 4.3% outcome language. There are zero confirmed McLeod Alpha matches.

## Recurring and Contradictory Evidence

- A proposed 563-put gate gives incompatible red-candle and green-candle
  conditions; no fill follows in that discussion window.
- One named source stated there was no real setup for the later put scalp, only
  downside momentum and stated support near 562.65.
- The $565 call pick-of-the-day fields are caption-inconsistent and are not
  counted as a presenter position or verified trade.
- The caption stream is auto-generated and has no reliable speaker diarization.

## Candidate Hypotheses

1. Test support and downside-momentum labels only with timestamped bar data,
   defined levels, and executable option marks.
2. Separate service picks, participant reports, and named presenter positions
   before any outcome aggregation.
3. Test rebound-failure context only after independently reconstructing the
   underlying level and contract execution path.

## Instrumentation Gaps

- Visual chart/order review and speaker attribution.
- Contract symbols, order identifiers, position sizes, and broker fills.
- Timestamped underlying bars, option bid/ask/last data, fees, and MFE/MAE.
- Exact strike linkage for the 563/562/564 sequence and canonical ledger mapping.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, or risk-policy change is
authorized from this recording. All source-reported results are research-only.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`. Retain bounded claims only for later
replay with independent market, execution, and ledger evidence.