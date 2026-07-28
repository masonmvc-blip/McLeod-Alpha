# McLeod Alpha Research Report: 2025-04-09 Trading Room

## Executive Assessment

Authorized browser captions cover 527 distinct cues from 00:00:00 through
01:14:27 of a 01:16:51 asset. The transcript panel itself exposed no later cue,
so coverage is 97%, not complete. The source repeatedly treated high volatility
as a no-trade or reduced-risk condition and required an OMG close before acting.

It then explicitly described a proposed two-contract 501-call position as a
simulated experiment, with captioned 18.27 entry, 18.93 target/fill discussion,
and later 18.99 fill language. It is not a verified live execution, and the
unobserved terminal portion could qualify it further.

## Source Lineage and Evidence Quality

- Recording: Day Trade SPY post `39400`, "Trading Room Video Recording - April
  9, 2025."
- Source: authenticated Vimeo asset `1074075369`, English auto-generated
  captions collected in the authorized browser transcript panel.
- Transcript coverage: 97%, 00:00:00 through 01:14:27; transcript panel ended
  144 seconds before asset duration.
- Visual review, speaker attribution, underlying bars, option marks, broker
  executions, and canonical ledger mapping: unavailable.
- Evidence tier: C, `TRANSCRIPT_PARTIAL_VISUAL_UNAVAILABLE`.

## Evidence Timeline

| Recording time | Evidence | Research interpretation |
| --- | --- | --- |
| 00:11:02-00:17:22 | Source advised waiting for volatility to decline and described premium/spread risks. | Candidate gate, not a validated trading rule. |
| 00:15:03-00:15:18 | Source said an OMG close had not occurred and would reconsider at a close. | Candidate admission condition requiring deterministic labels. |
| 00:18:31 | Source expressly called the proposed options purchase a simulated, not real, trade. | Do not treat subsequent values as live execution evidence. |
| 00:22:03-00:24:16 | Source described two 501 calls at a captioned 18.27 and waited for a close/retest before an OMG entry. | Source experiment and setup language only. |
| 00:26:29-00:28:31 | Source described 78% Fibonacci retracement and OMG-line retest/hold behavior. | Structural labels need bar reconstruction. |
| 00:31:51-00:35:29 | Source discussed a target around 18.93, lack of expected fill, then a captioned 18.99 fill. | Preserve the target/fill ambiguity and simulation boundary. |

## Presenter-Reported Trades

| Source trade | Instrument and stated setup | Reported entry | Reported exit/outcome | Reconciliation status |
| --- | --- | --- | --- | --- |
| DTS-20250409-T01 | Simulated two-contract 501-call OMG experiment | 18.27 captioned source value | 18.93 target/fill discussion; 18.99 later source fill language | Explicitly simulated; no broker/order evidence. |

## Ledger Reconciliation

There is no canonical ledger mapping, broker execution, underlying bar, option
mark, or excursion data. The source itself says this was a simulated trade.
Captioned values cannot establish a live fill, P&L, or McLeod Alpha match, and
the transcript ends 144 seconds before asset duration.

## Candidate Hypotheses

1. Test high-implied-volatility and spread filters against deterministic OMG
   labels using executable option marks, actual fills, costs, and an ungated
   baseline.
2. Test OMG close, retest, and hold conditions with deterministic bars rather
   than source narration or a single simulated example.
3. Test Fibonacci-retracement confluence only with explicit calculation rules,
   MFE/MAE, target-hit rates, and out-of-sample replay.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, averaging, or risk-policy change
is authorized from this recording.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.