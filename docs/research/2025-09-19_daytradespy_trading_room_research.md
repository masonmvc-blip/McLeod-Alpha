# McLeod Alpha Research Report: 2025-09-19 Trading Room — Post 41659

## Executive Assessment

September 19 was a volatile expiration Friday with unreliable simulator
behavior and conflicting exposure. The formal September 26 662-put OMG entered
at `4.17` with a `4.42` target but remained open near break-even at the terminal
cue. The September 26 661 puts carried from September 18 also remained open,
with the presenter noting the original `5.65` entry while they traded near
`3.30`.

A failed attempt to enter a call scalp later proved to have filled at `4.17`,
creating an unintended position opposite the puts. The presenter sold that
first call lot at `4.31`, then added calls at `4.34`; the added lot remained
open with a `4.45` objective. The published pick was reported successful, but
the presenter explicitly said he could not trade it. This session is primarily
an order-state and gross-exposure failure case, not a clean winning-trade
example.

## Source Lineage and Evidence Quality

- Post `41659`; Vimeo `1120944307` (`9-19 TR`), duration `01:34:18`.
- Complete authorized VTT: 1,559 cues, `00:00:00-01:34:14`.
- Player was set to `0%` volume before any progress. A transcript-control
  interaction briefly advanced the muted player to `00:04`; it was immediately
  paused. No audio played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Expiration Friday opened with a premarket upside surge, then reversed and
  oscillated around the OMG range.
- The OMG boundaries were approximately `661.78-662.64`.
- The presenter described himself as tired, frustrated, and not at full
  capacity while the simulator responded slowly.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:15:43-00:16:24 | Sep. 26 662 puts entered `4.17`; target `4.42`. | Formal downside OMG entry. |
| 00:27:03-00:29:13 | Attempted 662-call scalp appeared missed because of simulator latency. | Order state was not understood. |
| 00:28:06-00:30:00 | Published pick was reported successful; presenter could not trade it. | Modeled pick only. |
| 00:36:28-00:38:03 | Presenter discovered the 662 calls had filled `4.17`. | Unintended opposing position. |
| 00:44:59-00:45:25 | Added 662 calls at `4.34`; average cited near `4.25`. | Increased opposing call exposure. |
| 00:46:09-00:46:25 | First `4.17` call lot sold `4.31`. | Source-reported 14-cent gain. |
| 01:13:39-01:13:59 | Sep. 26 661 puts from Sep. 18 still open from `5.65`, near `3.30`. | Large unresolved carry loss. |
| 01:31:41-terminal | OMG puts, older 661 puts, and added calls remained open. | Unreconciled opposing terminal exposure. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250919-P41659-T01 | Sep. 26 661 puts carried from Sep. 18 | `5.65` | unresolved; near `3.30` late |
| DTS-20250919-P41659-T02 | Sep. 26 662 puts; downside OMG | `4.17` | unresolved; target `4.42` |
| DTS-20250919-P41659-T03 | Published pick | terms unavailable | reported worked; presenter did not trade |
| DTS-20250919-P41659-T04 | Sep. 26 662 calls; unintended scalp | `4.17` | `4.31` |
| DTS-20250919-P41659-T05 | Sep. 26 662 calls; added lot | `4.34` | unresolved; objective `4.45` |

## Entry and Exit Lessons

1. An unacknowledged order must remain blocking until its state is resolved.
2. Opposing calls and puts can conceal gross exposure without reducing
   execution risk.
3. Fatigue and frustration should be observable admission controls.
4. A modeled pick is not a presenter fill.
5. A formal OMG cannot enter completed-win statistics while still open.

## Contradictions and Process Risks

- The presenter first described the call entry as missed, then discovered it
  remained open.
- He acknowledged diminished readiness but continued adding exposure.
- A favorable exit on the first call lot coexisted with two unresolved put
  positions and another unresolved call lot.
- The older 661 puts had lost roughly `2.35` in quoted premium from entry to
  the late-session quote, but no terminal fill was supplied.

## Falsifiable Replay Hypotheses

1. An order-acknowledgement gate prevents unintended positions.
2. A readiness gate blocks new trades during self-reported impairment.
3. Gross-exposure limits outperform net-direction accounting.
4. A room-boundary close rule reduces unresolved OMG exposure.
5. Fill-qualified reporting lowers apparent pick success.

## Ledger and Instrumentation Gaps

No full visual review, pick terms, exact position sizes, terminal fills,
broker/simulator ledger, independent P&L, aggregate Greeks, executable option
paths, synchronized bars, exact MFE/MAE, spreads, slippage, or complete fees is
available.

## Explicit Non-Changes

No live OMG, readiness, order-state, gross-exposure, holding-time, sizing,
direction, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
