# McLeod Alpha Research Report: 2025-03-18 Trading Room

## Executive Assessment

Authorized captions cover 1,489 cues from 00:00:04 through 01:12:28 of a
01:13:04 recording. The first five seconds and final approximately 36 seconds
are unknown. The source reported several March 21 put sequences, including a
564-put scalp from 6.21 to 6.53. It also explicitly identified an erroneous
order sequence to ignore; that sequence is excluded rather than treated as a
trade. All retained results remain source assertions.

## Source Lineage and Evidence Quality

- Recording: Day Trade SPY post `38935`, "Trading Room Video Recording - March
  18, 2025."
- Source: `https://daytradespy.com/38935/trading-room-video-recording-march-18-2025/`
- Authorized source: signed Vimeo English auto-generated caption stream.
- Transcript coverage: 99%, 00:00:04 through 01:12:28; beginning and final
  approximately 41 seconds combined are `UNKNOWN`.
- Visual review, speaker attribution, underlying bars, option marks, broker
  executions, and canonical ledger mapping: unavailable.
- Evidence tier: C, `PARTIAL_AUTHORIZED_TRANSCRIPT`.

## Evidence Timeline

| Recording time | Evidence | Research interpretation |
| --- | --- | --- |
| 00:29:43-00:30:23 | Source described conflicting orders and explicitly said "ignore that one." | Excluded error sequence, not a retained trade. |
| 00:30:53-00:31:41 | Source reported nine Mar. 21 564 puts from 6.21 to 6.53, later recapped as 09:35 to 09:37. | Source-reported completed put scalp. |
| 00:33:40-00:34:25 | Source said it held 560 puts from 5.54 and reported a 5.80 fill. | Source claim; size absent. |
| 00:42:28-00:44:13 | Source waited for a better test of a referenced 10-level and then price behavior at the 20 MA. | Candidate technical wait/confirmation context; chart labels unavailable. |
| 00:45:32-00:46:01 | Source said trades were closed and described 560 puts from 5.54 at 09:46 to 5.80 at 09:55. | Separate recap; matching values are not enough to prove identity with earlier claim. |
| 01:00:22-01:01:38 | Source recapped several 562- and 560-put sequences with entries/exits and unclear size/dollar statements. | Retained separately; captions contain contradictory numerical detail. |

## Presenter-Reported Trades

| Source trade | Instrument and stated setup | Reported entry | Reported exit/outcome | Reconciliation status |
| --- | --- | --- | --- | --- |
| DTS-20250318-T01 | Nine Mar. 21 564 puts; first trade | 6.21 at 09:35 | 6.53 at 09:37; $279 net after $9 commission stated | Source-reported; later 6.50 mention conflicts and is not selected. |
| DTS-20250318-T02 | 560 puts | 5.54 | 5.80 fill stated | Size absent; keep separate from matching recap. |
| DTS-20250318-T03 | 562 Mar. 21 puts | 6.16 at 09:50 | 6.50 at 09:52 | Size and dollar outcome absent. |
| DTS-20250318-T04 | 562 puts; trade number two | 6.18 at 09:51 | 7.27 at 10:03 | Captioned dollar statement is ambiguous; size unavailable. |
| DTS-20250318-T05 | 562 puts | 5.95 at 09:40 | 6.15 at 09:44 | Size absent; do not merge with earlier ambiguous entry discussion. |

## Ledger Reconciliation

No canonical ledger mapping, broker executions, option marks, underlying bars,
or excursion data was available. An explicit erroneous order sequence was
excluded. Matching values in the 560-put commentary are not enough to prove one
position lifecycle. There are zero confirmed McLeod Alpha matches.

## Recurring and Contradictory Evidence

- Recurring: source described waiting for a meaningful technical test and price
  behavior near a moving average before new participation.
- Recurring: exits were described as taking a healthy profit rather than getting
  greedy; no reusable stop rule was stated.
- Contradiction: source self-corrected 650 to 564 puts and later mentioned 6.50
  after explicitly summarizing 6.21 to 6.53.
- Contradiction: earlier captions alternated between receiving/not receiving an
  entry and saying "this isn't real"; those claims are excluded.

## Candidate Hypotheses

1. Test whether waiting for a defined support/moving-average test improves put
   scalp selection versus immediate continuation entries.
2. Test pre-defined profit-taking near extension levels against a hold-for-more
   baseline using executable option marks and fills.
3. Track and reject erroneous order submissions explicitly before evaluating any
   trade sequence or performance attribution.

## Instrumentation Gaps

- First five seconds and final approximately 36 seconds of recording.
- Visual chart review, speaker attribution, and order-ticket evidence.
- Timestamped underlying bars, option quotes, broker fills, and commissions.
- MFE/MAE, order-error logs, and canonical ledger mapping.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, or other trading-policy change is
authorized from this recording. The source's put outcomes and profit-taking
language are external observations only.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`. Retain only bounded source claims and
the explicit error exclusion for later replay with independent evidence.