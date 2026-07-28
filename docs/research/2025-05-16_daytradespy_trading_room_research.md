# McLeod Alpha Research Report: 2025-05-16 Trading Room

## Executive Assessment

May 16 contains three useful execution studies. First, a downside OMG waited
for the close, bounce, and rejection at the 10-MA; May 23 590 puts entered at
`4.31` and the contemporaneous transcript reports a `4.57` target fill. A later
summary says `5.37`, creating a material source conflict that cannot be resolved
without order records. Second, real May 23 591 calls entered at `4.94` and
eventually reached `5.13`, but only after a scheduled sentiment release caused
a sharp adverse move and a long recovery. Third, an explicitly simulated,
high-risk 590-put scalp moved from `4.43` to `4.53`.

The best lesson is to align holding time with event risk. The 591-call setup may
have been technically sound, but entering shortly before scheduled Michigan
sentiment exposed a small scalp to an avoidable binary shock. The target
eventually filled; that outcome does not erase the admission error.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40284`; authenticated Vimeo asset `1085803816`, `5-16
  TR.mp4`.
- Duration `01:23:28`; 549 recovered timestamped cues span
  `00:00:00-01:23:22`.
- The transcript explicitly identifies Thinkorswim simulation failures and
  switches to a real account for one call trade.
- Visual orders, broker logs, synchronized bars, and option paths unavailable.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- SPY tested the prior-day gap near `590.46` and repeatedly rotated around
  `590-592`.
- University of Michigan sentiment and inflation expectations were scheduled
  for 10:00 Eastern; the release produced a sudden downside bar.
- Friday expiration, profit taking, and resistance near `591.40-592` created
  late-session congestion.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:13:24-00:15:49 | A downside OMG close occurred at gap support; the source waited for the bounce to reject the 10-MA. | Confirmation avoided selling the first support touch. |
| 00:15:58-00:21:48 | May 23 590 puts filled at `4.31`, target `4.57` above the next underlying low; the source reported the target fill. | Structural room and immediate exit order were explicit. |
| 00:31:46-00:35:33 | Simulation orders failed repeatedly; the source switched to a real account and bought May 23 591 calls at `4.94`, target `5.13`. | Platform/account state materially affected execution. |
| 00:39:29-00:41:24 | Sentiment and inflation data caused a sharp adverse move immediately after the call entry. | Scheduled-event exposure was not incorporated into admission. |
| 01:04:55 | A later recap said the 590 puts sold at `5.37`, conflicting with the contemporaneous `4.57` target/fill. | Result must remain disputed, not silently chosen. |
| 01:06:17-01:08:56 | The real 591 calls finally filled at `5.13`; price reversed after reaching the Fibonacci target. | The target was effective, but time-underwater and event risk were substantial. |
| 01:09:37-01:10:16 | The source described price as a blender and required a clean break before any weekend call hold. | Explicit congestion/no-trade logic improved discipline. |
| 01:16:02-01:17:16 | An explicitly non-real 590-put experiment entered at `4.43`, seeking ten cents. | Correctly classified as simulation. |
| 01:17:50-01:18:41 | The source called the put trade "dancing in front of a steamroller" and identified a better entry after a 10-MA test. | Premature countertrend admission was acknowledged. |
| 01:20:43-01:21:31 | The simulated puts reached `4.53`; the source reported the exit and warned the prior low could hold. | Small target matched the risky countertrend premise. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250516-T01 | May 23 590 puts; downside OMG rejection | `4.31` | `4.57` contemporaneous; later recap says `5.37` |
| DTS-20250516-T02 | May 23 591 calls; real Fibonacci recovery | `4.94` | `5.13` |
| DTS-20250516-T03 | May 23 590 puts; simulated countertrend experiment | `4.43` | `4.53` |

Unfilled simulation orders and participant trades are excluded.

## Entry and Exit Lessons

1. Wait for the post-close bounce to reject before entering at support.
2. Check the economic calendar before admitting a scalp.
3. A later target fill does not excuse uncontrolled event exposure.
4. Platform and account-mode failures are part of execution risk.
5. Preserve source conflicts rather than selecting the more favorable result.
6. Avoid new trades when price action is explicitly described as a blender.

## Contradictions and Risks

- The first trade's exit is reported as both `4.57` and `5.37`.
- The call was entered shortly before known event risk despite a small target.
- A simulated trade was initially discussed alongside real-account actions,
  making account-state labeling essential.
- The source advised a participant not to cut call losses while also describing
  strong Friday congestion and uncertain weekend conditions.

## Falsifiable Replay Hypotheses

1. Compare OMG entries after bounce rejection with immediate close entries.
2. Exclude new scalps within a fixed window before scheduled tier-one releases.
3. Measure target-fill probability against time-underwater and MAE.
4. Compare countertrend entries before and after a 10-MA retest.

## Ledger and Instrumentation Gaps

Broker orders are required to resolve the `4.57/5.37` conflict and verify
account mode. Exact symbols, sizes, spreads, fees, bars, bid/ask paths, MFE/MAE,
and ledger links are unavailable.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, or risk-policy change
is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
