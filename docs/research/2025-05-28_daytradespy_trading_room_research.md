# McLeod Alpha Research Report: 2025-05-28 Trading Room

## Executive Assessment

This session shows the difference between a disciplined first trade and risk
added after success. The first May 30 592-call trade waited for price to recover
and press resistance, entered 18 contracts at `3.90`, and exited at `4.37`.
The source states a `$836` net result after commissions. Although its target
was repeatedly raised, it was closed while the move still had momentum.

The immediate re-entry in the same 592 calls at `4.35` was weaker. It duplicated
the same directional exposure after the first profit, had an arbitrary `4.50`
target, and was retained overnight with no defined loss boundary despite
NVIDIA event risk. The next recording confirms that this position became a
large distraction and loss. The contrast is especially important because the
presenter advised participants in expiring puts to accept a smaller loss rather
than risk a larger event-driven loss.

The upside OMG in June 6 593 calls entered at `6.43` after a pullback and was
later declared successful, but the transcript does not preserve a specific exit
fill. A late June 6 590-put trade entered at `5.86` also remained unresolved
despite an available 10-15 cent gain and nearby support.

The strongest reusable lesson is to stop adding same-direction risk after a
successful opening trade unless a new setup has independent confirmation,
structural room, and a precommitted loss boundary.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40394`; authenticated Vimeo asset `1088498868`,
  `5-28 TR.mp4`.
- Duration `01:12:29`; 460 recovered timestamped cues span
  `00:00:00-01:12:09`.
- Visual orders, broker evidence, synchronized SPY bars, and executable option
  paths remain unavailable.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- The source began with an upside bias tied to NVIDIA expectations.
- A possible head-and-shoulders structure and light volume made follow-through
  less certain.
- Price produced an early upside break, then deteriorated into a slower,
  support-constrained session with scheduled data and overnight event risk.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:09:58-00:10:41 | The first position was mistakenly calculated as 65 contracts, then corrected to 18 before entry. | The correction preceded the fill, but shows a preventable sizing-control failure. |
| 00:12:18-00:18:33 | Eighteen May 30 592 calls entered at `3.90`; targets moved from `4.10` to `4.15` and `4.25`; exit was `4.37`. | Confirmation and momentum produced the best fully described trade, though target changes were discretionary. |
| 00:18:53-00:21:13 | The upside OMG waited for a pullback, then June 6 593 calls entered at `6.43`, target `6.82`. | Unlike a first-contact entry, admission followed a confirmed close and test. |
| 00:20:40-00:22:11 | Sixteen May 30 592 calls re-entered at `4.35`; the target `4.50` was described as pulled from the air. | The second call duplicated exposure without a fresh structural objective. |
| 00:32:13-00:33:24 | Participants holding prior-day expiring puts were advised to take a smaller loss rather than risk NVIDIA and decay. | This was sound risk logic but was not applied consistently to the presenter's own carried call. |
| 00:38:16 | The published pick reportedly entered June 6 592 calls at `6.47` and hit `6.86`. | Benchmark evidence only; it is not counted as a presenter-reported room trade. |
| 00:54:52-01:06:38 | June 6 590 puts entered at `5.86`, target `6.14`; the presenter later acknowledged an available 10-15 cent gain but reported no exit. | Nearby support and weak downside pressure argued for a bounded exit. |
| 01:07:23-01:08:15 | The second 592-call trade was deliberately held for the next day with no definite exit price; the OMG was declared successful. | A profitable day was converted into overnight event exposure and incomplete reconciliation. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250528-T01 | 18 May 30 592 calls; opening follow-through | `3.90` | `4.37`; source states `$836` net |
| DTS-20250528-T02 | June 6 593 calls; upside OMG | `6.43` | Declared successful; exact exit fill unavailable |
| DTS-20250528-T03 | 16 May 30 592 calls; same-direction re-entry | `4.35` | Carried overnight; no stop or exit reported |
| DTS-20250528-T04 | June 6 590 puts; late downside test | `5.86` | Unresolved; about 10-15 cents favorable was discussed |

The published pick and participant results are excluded from
presenter-reported trades.

## Entry and Exit Lessons

1. The first call combined recovery, resistance pressure, and visible momentum;
   those conditions were stronger than the later desire to repeat the win.
2. A new trade after a win needs a new thesis and structural target, not merely
   the same contract at a higher premium.
3. The OMG admission sequence—close, pullback, confirmation—was stronger than
   first-contact anticipation.
4. When support constrains a put, a small available gain is more defensible than
   holding for an arbitrary premium target.
5. Event risk and time decay should trigger the same loss discipline for the
   presenter that is recommended to participants.

## Contradictions and Process Risks

- The first size calculation was 65 contracts before correction to 18.
- The first call target was raised repeatedly; the second target was explicitly
  arbitrary.
- The room advised smaller-loss exits ahead of NVIDIA while retaining its own
  losing call through the event.
- The late put recognized support and an available gain but did not report an
  exit.
- “OMG trade worked” does not establish an executable exit premium.
- Multiple open positions made aggregate directional exposure unclear.

## Falsifiable Replay Hypotheses

1. After a completed opening winner, prohibit same-direction re-entry until a
   new consolidation and breakout are confirmed.
2. Compare the second 592-call result with a rule that ends trading after the
   first target-exceeding winner.
3. Test OMG entries after close-pullback-confirmation against entries on the
   first boundary touch.
4. Exit puts at the first defended support when downside volume does not expand.
5. Require every overnight option hold to have a recorded maximum loss and
   event-risk rationale before the session ends.

## Ledger and Instrumentation Gaps

No broker orders, exact OMG exit, final put exit, executable bid/ask history,
fees beyond the first stated calculation, MFE/MAE, synchronized bars, or
aggregate exposure exists. The carried call is reconciled only by later
recordings.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, hedging, expiration, or risk-policy
change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
