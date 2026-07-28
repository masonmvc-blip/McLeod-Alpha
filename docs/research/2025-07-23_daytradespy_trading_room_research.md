# McLeod Alpha Research Report: 2025-07-23 Trading Room — Post 41024

## Executive Assessment

July 23 began near all-time highs before existing-home-sales data and
Alphabet/Tesla earnings. The formal downside OMG used next-week 631 puts,
entered at `5.37`, and exited at `5.69`. A second put lot entered at `5.39`;
the platform reportedly exited both lots together at `5.69`, an unintended
all-position action that obscured the intended second target.

The room then reversed into calls. A next-week 630-call scalp entered `6.05`
and exited `6.17`. Fifteen August 1 632 challenge calls entered `4.90`; their
target moved `5.15` to `5.24` and back to `5.15`, and an end-of-day exit plan
became an overnight earnings hold. Another call entry near `6.23` remained
unresolved. This conversion from scalp to earnings carry is the session's
largest governance concern.

## Source Lineage and Evidence Quality

- Day Trade SPY post `41024`, published July 23, 2025.
- Authenticated Vimeo asset `1103883906`, title `7-23 TR`, duration
  `01:18:00`.
- Complete authorized English auto-generated VTT: 1,497 cues span
  `00:00:00-01:17:46`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- SPY approached an all-time high near `631.91`; existing-home-sales data was
  due at 10:00, with Alphabet and Tesla earnings after the close.
- The upper OMG boundary was approximately `631.81`.
- Downside discussion moved between `631.06` and `630.41`; `630.41` became the
  operational lower line, but the source did not present a clean frozen-boundary
  artifact.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:08:55 | Overnight call holders were advised to take profits. | This conflicts with the later decision to carry underwater calls overnight. |
| 00:24:43-00:35:06 | August 1 631 puts entered `5.37`, targeted `5.69`, and exited `5.69`. | A completed formal downside OMG winner by source narration. |
| 00:29:31-00:35:06 | A second 631-put lot entered `5.39`; the platform reportedly exited everything at `5.69`. | An unintended all-position exit reveals simulator/order-control risk. |
| 00:45:00-00:48:11 | Next-week 630 calls entered `6.05` and exited `6.17`. | A completed discretionary reversal scalp. |
| 00:45:00 onward | Fifteen August 1 632 challenge calls entered `4.90`; target began at `5.15`. | The position later became an earnings carry without a predeclared stop. |
| 01:03:57 onward | Another likely 630-call position entered `6.23` with a `6.37` target. | Contract narration and terminal exit were incomplete, so the trade remains unresolved. |
| later recap | A non-official July 25 631-call signal modeled entry `2.25` at 10:11 and target `2.36`, reportedly reaching `2.42` at 10:29. | Retrospective signal outcome is separate from broker-verified execution. |
| terminal room | The 632-call target moved `5.15` to `5.24` and back; an EOD exit plan changed to an overnight hold based on Alphabet earnings. | The strategy horizon and event risk changed after entry. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250723-P41024-T01 | August 1 631 puts; formal downside OMG lot 1 | `5.37` | `5.69` |
| DTS-20250723-P41024-T02 | August 1 631 puts; duplicate/formal lot 2 | `5.39` | reportedly included in all-position exit at `5.69` |
| DTS-20250723-P41024-T03 | Next-week 630 calls; discretionary scalp | `6.05` | `6.17` |
| DTS-20250723-P41024-T04 | August 1 632 calls; challenge, 15 contracts | `4.90` | unresolved; converted to overnight earnings hold |
| DTS-20250723-P41024-T05 | Likely next-week 630 calls; later discretionary entry | `6.23` | unresolved; target `6.37`, exact contract not fully evidenced |
| DTS-20250723-P41024-T06 | July 25 631 calls; retrospectively modeled non-official signal | modeled `2.25` | modeled target `2.36` reached; reported high `2.42` |

## Entry and Exit Lessons

1. Freeze upper and lower boundaries before eligibility and retain every
   revision with its timestamp.
2. Simulator and broker controls must distinguish target-lot exits from
   all-position exits.
3. A scalp cannot become an overnight earnings position without a new,
   explicit risk decision and maximum loss.
4. Do not move targets after entry without recording the rule and
   counterfactual original outcome.
5. Aggregate sequential puts and later calls to measure total premium and
   directional reversals.

## Contradictions and Process Risks

- The downside boundary discussion was fluid between `631.06` and `630.41`.
- A delayed simulator fill and unintended exit-all action changed formal-trade
  execution.
- Profitable put exposure was followed by multiple call positions without an
  aggregate exposure ledger.
- The challenge-call target moved `5.15` → `5.24` → `5.15`.
- An intended end-of-day exit became an overnight earnings hold.
- Early advice to sell overnight calls conflicted with later advice to hold
  underwater calls through earnings.
- The later `6.23` call lacked a fully evidenced contract and terminal exit.

## Falsifiable Replay Hypotheses

1. Freeze OMG boundaries before the first eligible bar.
2. Require lot-specific exit controls and reject unintended exit-all events.
3. Enforce an immutable day-trade horizon unless a separately approved
   overnight-risk ticket is completed.
4. Score original and revised targets separately.
5. Cap aggregate premium risk across reversal trades.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, lot quantities beyond the
challenge calls, exact contract for the `6.23` entry, terminal call exits,
overnight outcome, aggregate Greeks/premium risk, synchronized bars, executable
option paths, MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, overnight-hold,
target-revision, boundary, or order-control change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
