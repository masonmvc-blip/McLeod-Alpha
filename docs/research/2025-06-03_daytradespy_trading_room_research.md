# McLeod Alpha Research Report: 2025-06-03 Trading Room

## Executive Assessment

June 3 produced a strong upside session, but its best evidence is about entry
quality. The opening 15-contract June 6 593-call position filled accidentally
at `4.24` while the presenter tried to cancel it, then sold at `4.51`. A
parallel real trade waited longer and moved from `4.13` to `4.35`. The upside
OMG waited for a five-minute close, pullback, and one-minute confirmation,
entering June 6 592 calls at `4.72` and exiting at `5.00`.

Later, repeated call entries continued to work as SPY ground higher: real 592
calls from `4.93` to `5.15` and a second 15-contract 593-call model trade from
`4.43` to a source-adjudicated `4.55`. Yet the source described several targets
as numbers “out of the air,” experienced repeated simulator order rejection,
and reported another 593-call play without a complete entry/exit ledger.

The strongest lesson is that a trending market can reward weak process.
Accidental fills, arbitrary targets, and incomplete records must remain process
failures even when every call eventually exits profitably.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40477`; authenticated Vimeo asset `1090242477`,
  `6-3 TR.mp4`.
- Duration `01:12:44`; 442 timestamped cues span `00:00:00-01:09:53`.
- Complete authorized transcript; visual orders, broker evidence, synchronized
  bars, and executable option paths unavailable.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- SPY surged at the open into prior-session and longer-term resistance.
- Pullbacks repeatedly held the 50 EMA and cup-with-handle breakout region.
- The market eventually ground through resistance rather than producing a
  clean one-direction impulse.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:07:39-00:09:54 | The presenter chased the surge, tried to cancel, but filled 593 calls at `4.24`. | Positive P&L cannot convert an accidental fill into a valid entry. |
| 00:11:04-00:19:24 | A real 593-call scalp waited for the pullback, entered `4.13`, exited `4.35`. | The lower, confirmed entry was cleaner than the accidental model fill. |
| 00:12:03-00:20:01 | Upside OMG waited for close and confirmation; 592 calls entered `4.72`, exited `5.00`. | This is the strongest complete setup sequence. |
| 00:19:49-00:20:26 | The accidental `4.24` trade exited at `4.51`; source stated `$395` net. | Economics are source-reported and unreconciled. |
| 00:21:35-01:05:19 | Real 592 calls entered `4.93` and eventually sold `5.15`. | The long hold crossed repeated resistance tests. |
| 00:22:26-01:05:33 | Second model 593 calls entered `4.43`; rejected sell orders led to a bid-based `4.55` success ruling. | Fill policy was adjudicated after platform failure. |
| 00:56:53-01:06:25 | Another 593-call play was reported taken out, but entry and exit premiums were not preserved. | Directional success is not measurable performance. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250603-T01 | 15 June 6 593 calls; accidental model fill | `4.24` | `4.51` |
| DTS-20250603-T02 | June 6 593 calls; real pullback scalp | `4.13` | `4.35` |
| DTS-20250603-T03 | June 6 592 calls; upside OMG | `4.72` | `5.00` |
| DTS-20250603-T04 | June 6 592 calls; real continuation | `4.93` | `5.15` |
| DTS-20250603-T05 | 15 June 6 593 calls; second model trade | `4.43` | `4.55` source-adjudicated |
| DTS-20250603-T06 | June 6 593 calls; late/pick call play | Unavailable | Reported taken out; premiums unavailable |

## Entry and Exit Lessons

1. Cancelled-intent fills are operational incidents, not valid model entries.
2. Close-pullback-confirmation produced the cleanest OMG admission.
3. A lower entry after a pullback materially improves room to resistance.
4. Targets need a structural basis stated before entry.
5. Missing premiums disqualify a trade from performance statistics.

## Contradictions and Process Risks

- The source warned against chasing but the first fill occurred during a chase.
- Several target prices were explicitly arbitrary.
- Simulator rejection produced retrospective bid-based success.
- The uptrend rewarded every call, masking the fragility of entry discipline.
- One completed call lacked enough ledger data to evaluate.

## Falsifiable Replay Hypotheses

1. Compare accidental/chased entries with the first confirmed pullback.
2. Test close-pullback-confirmation against first-contact OMG entry.
3. Use first structural resistance rather than arbitrary premium increments.
4. Freeze simulator fill rules before the session.
5. Exclude incomplete-ledger trades from all expectancy calculations.

## Ledger and Instrumentation Gaps

No broker orders, deterministic simulator rules, executable bid/ask paths,
synchronized bars, MFE/MAE, complete fees, or complete late-call ledger exists.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, or risk-policy change
is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
