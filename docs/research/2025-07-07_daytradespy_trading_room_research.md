# McLeod Alpha Research Report: 2025-07-07 Trading Room — Post 40838

## Executive Assessment

July 7 began with a disciplined challenge/real-call sequence. Twenty-two July
11 625 calls entered at `3.27` and sold `3.50`, reporting `$496` after
commission; a real July 11 624-call scalp entered `3.92` and sold `4.04`.
John's separate 623 puts entered too early at `3.76` but later reported a gain.

The formal OMG exposes a more important governance failure. July 11 624 calls
entered at `4.08`. A trailing-stop demonstration actually took the simulated
position out at `4.01`; the loss was then treated as a demonstration artifact,
the model position was repurchased, and its original `4.08` basis and `4.32`
target were restored. The July 8 source says the OMG and published pick were
ultimately reported as end-of-day losses. A parallel real 624-call position
was doubled at a lower premium, averaged to `3.96`, and remained unresolved.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40838`, published July 7, 2025.
- Authenticated Vimeo asset `1099388303`, title `TR July 7`, duration
  `01:08:54`.
- Complete authorized English auto-generated VTT: 1,385 cues span
  `00:00:00-01:08:20`.
- Cross-day resolution is taken only from the complete July 8 source.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Tariff letters, the August 1 effective date, the July 9 negotiation deadline,
  and a sharply reduced probability of a July rate cut framed the session.
- SPY gapped down, bounced from early support, then oscillated within a broad
  range. Approximate OMG boundaries were `623.63` and `622.94`.
- The session repeatedly shifted between rounded-bottom recovery and renewed
  downside, making direction and admission timing consequential.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:11:54-00:12:10 | Prior-Thursday puts were said to have closed for a very nice profit. | Cross-session trade remained under-specified. |
| 00:13:18-00:14:27 | Twenty-two July 11 625 challenge calls entered `3.27`; target moved from `3.43` to `3.50`. | Anticipatory recovery entry preceded formal OMG confirmation. |
| 00:16:11-00:16:55 | Real July 11 624 calls entered `3.92`, target eventually `4.10`. | Parallel discretionary exposure shared the recovery thesis. |
| 00:25:21-00:26:56 | John entered July 11 623 puts at `3.76`, target `4.02`, then admitted the bar should have closed first. | Explicit premature entry; later outcome is not proof of valid admission. |
| 00:29:41-00:32:14 | Challenge calls sold `3.50` (`$496` net); real calls sold `4.04`. | Both anticipatory call positions closed before the formal setup. |
| 00:33:13-00:34:21 | A qualifying upside close activated July 11 624 OMG calls at `4.08`, target `4.32`. | Named setup had explicit admission and objective. |
| 00:35:24-00:35:40 | A second real 624-call position entered `4.10`. | New same-direction exposure was added near the formal entry. |
| 00:36:56-00:40:23 | A trailing-stop demonstration sold the OMG model at `4.01`; it was repurchased and reset to original basis/target. | Demonstration mutated the ledger, then the loss was administratively erased. |
| 00:41:06-00:41:23 | John said he took the gain on his puts; exact exit premium was not audible. | Premature trade ended favorably by source report. |
| 00:52:15-00:53:27 | OMG calls were near `3.58-3.60`; a `40%` cutoff at `2.45` or end-of-day close was discussed, alongside willingness to hold overnight. | Exit governance was internally inconsistent. |
| 01:04:12-01:07:16 | The real 624 calls added an equal tranche at `3.82`, average `3.96`, target `4.10`; position remained open. | Repair doubled exposure without a contemporaneous maximum loss. |
| July 8 source | The July 7 OMG and pick were reported as end-of-day losses. | Cross-day source resolves direction but not exact exit premiums. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250707-P40838-T01 | Prior-Thursday puts | unavailable | "very nice profit" reported |
| DTS-20250707-P40838-T02 | 22 July 11 625 calls; three-20 | `3.27` | `3.50`; `$496` net reported |
| DTS-20250707-P40838-T03 | July 11 624 calls; first real scalp | `3.92` | `4.04` |
| DTS-20250707-P40838-T04 | July 11 623 puts; premature discretionary | `3.76` | gain reported; exit premium unavailable |
| DTS-20250707-P40838-T05 | July 11 624 calls; formal upside OMG | `4.08` | demo stop `4.01`, reinstated, then end-of-day loss reported July 8 |
| DTS-20250707-P40838-T06 | July 11 624 calls; second real/repair | `4.10`, then equal tranche `3.82`; `3.96` average | unresolved; target `4.10` |
| DTS-20250707-P40838-T07 | Published pick | unavailable | end-of-day loss reported July 8 |

## Entry and Exit Lessons

1. A training demonstration must operate on a sandbox copy; it cannot mutate
   the canonical model ledger and then be ignored.
2. Re-entry after a real model stop is a new trade, not restoration of the
   original cost basis.
3. Premature puts and anticipatory calls must remain separate from formal OMG
   performance.
4. Repairing by doubling quantity requires a new aggregate-loss limit.
5. "Forty percent or end of day" conflicts with "hold overnight"; one
   predeclared rule must govern the outcome.

## Contradictions and Process Risks

- The OMG model realized a `4.01` stop during a demonstration, then the source
  reinstated the original `4.08` basis as though no exit occurred.
- The source alternated among a `40%` cutoff, end-of-day close, and overnight
  hold.
- The second real call position doubled at `3.82` and remained unresolved.
- John's puts entered before the intended bar close.
- The challenge target was moved from `3.43` to `3.50`.
- The July 8 source resolves the OMG and pick only as losses, without exact
  exit premiums; the real repaired calls remain unreconciled.

## Falsifiable Replay Hypotheses

1. Enforce immutable ledger events for every simulated fill, stop, and re-entry.
2. Compare close-confirmed entries with anticipatory calls and premature puts.
3. Apply an aggregate exposure/loss cap before any repair tranche.
4. Compare fixed end-of-day exits with predeclared overnight eligibility.
5. Measure repaired and unrepaired trades as distinct cohorts.

## Ledger and Instrumentation Gaps

No full visual review, broker or simulator event log, exact real quantities,
aggregate exposure, July 7 end-of-day exit premiums, published-pick entry,
synchronized bars, executable option paths, MFE/MAE, spreads, slippage, or
complete fees is available. The repaired real calls remain unresolved.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, repair, or risk-policy
change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
