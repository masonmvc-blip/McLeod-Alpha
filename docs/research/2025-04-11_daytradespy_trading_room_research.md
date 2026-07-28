# McLeod Alpha Research Report: 2025-04-11 Trading Room

## Executive Assessment

Authorized browser captions cover 456 cues from 00:00:01 through 01:10:46 of a
01:11:11 asset. The source separated a support hold from an OMG close, then
reported two April 17 call scalps and an OMG 530-call position. Stated prices,
P&L, and targets are source-only; the 13.14 OMG target has no confirmed exit in
the observed transcript.

## Source Lineage and Evidence Quality

- Recording: Day Trade SPY post `39432`, "Trading Room Video Recording - April
  11, 2025."
- Source: authenticated Vimeo asset `1074759029`, English auto-generated
  captions in the authorized browser transcript panel.
- Transcript coverage: 99%, ending 25 seconds before asset duration.
- Visual review, speaker attribution, underlying bars, option marks, broker
  executions, and canonical ledger mapping: unavailable.
- Evidence tier: C, `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Recording time | Evidence | Research interpretation |
| --- | --- | --- |
| 00:14:37-00:17:46 | Source described support holding but no OMG close, then a potential bounce. | Candidate admission distinction requiring bar reconstruction. |
| 00:21:58-00:24:53 | Source reported four April 17 524 calls at 14.50 and a 15.75 sale, with $496 stated. | Source-only outcome; no contract/order lineage. |
| 00:28:27-00:31:04 | Source said no OMG close, then reported four 530 calls at 12.05 and a 12.60 sale. | Retain close-condition tension and reported prices separately. |
| 00:34:11-00:35:37 | Source described an OMG 530-call re-entry at 12.40 and 13.14 target tied to 529.29 underlying. | Target is not a confirmed sale. |

## Presenter-Reported Trades

| Source trade | Instrument and stated setup | Reported entry | Reported exit/outcome | Reconciliation status |
| --- | --- | --- | --- | --- |
| DTS-20250411-T01 | April 17 524 calls, pivot target | 14.50 captioned source value | 15.75 captioned source value; $496 stated | No broker/order evidence. |
| DTS-20250411-T02 | April 17 530 calls, retracement hold | 12.05 captioned source value | 12.60 captioned source value | No broker/order evidence. |
| DTS-20250411-T03 | April 17 530 calls, stated OMG close/retest | 12.40 captioned source value | 13.14 target only | No confirmed sale. |

## Ledger Reconciliation

No canonical ledger mapping, broker fills, underlying bars, option marks, or
excursion data was available. Captioned prices and the stated $496 result cannot
establish realized P&L. The target for the OMG position remains distinct from a
reported fill. There are zero confirmed McLeod Alpha matches.

## Candidate Hypotheses

1. Test whether separating support hold from OMG close improves admission
   quality versus entering at first support contact.
2. Test pivot-target call scalps only with deterministic pivot labels, actual
   option fills, costs, MFE/MAE, and out-of-sample replay.
3. Test OMG close/retest entries with structural room and retracement labels
   against a first-break baseline.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, averaging, or risk-policy change
is authorized from this recording.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.