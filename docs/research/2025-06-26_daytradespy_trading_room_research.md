# McLeod Alpha Research Report: 2025-06-26 Trading Room

## Executive Assessment

June 26 produced several profitable source-reported call exits, including two
two-80 trades in July 3 610 calls. The formal OMG rule, however, was not
satisfied: price closed on the upper boundary rather than above it, and the
room explicitly said there was no OMG trade. Later, a discretionary 610-call
entry from 10:05 was retrospectively treated as an "effective" OMG and entered
into the model after the move was already favorable.

That distinction matters more than the reported profits. A discretionary trade
may be researched on its own merits, but backfilling it into a named setup
changes the denominator and makes the setup look better than the contemporaneous
rules allow. The best process lesson is to freeze signal identity at decision
time and preserve profitable non-signal trades as a separate class.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40741`; authenticated Vimeo asset `1096624721`,
  `TR June 26`.
- Duration `01:14:03`; 515 transcript cues (IDs `0-514`) span
  `00:00:00-01:13:10`.
- Complete authorized transcript; the player remained muted throughout review.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Mixed GDP, durable-goods, and jobless-claims data initially produced a
  widening, range-bound open.
- Better-than-expected pending-home-sales data became the upside catalyst.
- Price later broke to a new session high despite never producing the required
  close above the OMG boundary during the eligible decision window.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:09:43-00:09:59 | Prior-day real July 3 609 calls bought `4.73` sold `4.78`. | This clearly resolves the June 25 real 609-call position. |
| 00:13:07-00:39:36 | Sixteen July 3 610 calls entered at `4.18` for the two-80 trade and sold `4.34`; about `$246` net reported. | Bounded discretionary trade completed before the later breakout. |
| 00:18:08-00:29:04 | The room repeatedly stated that no OMG close had occurred. | The named setup remained inactive. |
| 00:39:10-00:40:37 | Pending-home-sales data triggered an upside move; prior-day 608 calls sold `5.50`, with a narrated 24-cent gain. | Likely June 25 carry resolution, but entry arithmetic and lot identity conflict. |
| 00:41:08-00:41:27 | A second two-80 trade entered July 3 610 calls at `4.30`; 15 were intended. | Later recap says only ten contracts actually filled. |
| 00:44:17-00:45:59 | Real July 3 610 calls entered `4.28` at narrated 10:05, target `4.54`; the pennant immediately failed. | A discretionary entry survived an adverse test, but it was not a formal OMG signal. |
| 00:55:33-00:57:58 | Price had closed on, not above, the OMG line; the room again said no OMG, while calling the earlier trade an "effective" OMG. | Contemporaneous rule and retrospective label diverged. |
| 01:05:02-01:06:54 | The earlier 10:05 entry was reconstructed as an OMG trade and added to the model after the fact. | Retrospective model admission creates look-ahead bias. |
| 01:07:11-01:10:45 | Real and two-80 calls exited profitably; the reconstructed model trade reached `4.54`; the published pick reached `4.40`. | Profitable outcomes do not cure the classification error. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250626-T00 | July 3 609 calls; June 25 real carry | `4.73` prior day | `4.78` |
| DTS-20250626-T01 | 16 July 3 610 calls; first two-80 trade | `4.18` | `4.34`; about `$246` net reported |
| DTS-20250626-T02 | July 3 608 calls; possible June 25 carry | likely `5.28`, but source arithmetic implies `5.26` | `5.50`; lot continuity unproven |
| DTS-20250626-T03 | 10 July 3 610 calls; second two-80 trade | `4.30` | `4.48`; about `$170` net reported |
| DTS-20250626-T04 | July 3 610 calls; real discretionary trade | `4.28` | source says `4.4x` at narrated 10:26; exact cents truncated |
| DTS-20250626-T05 | July 3 610 calls; retrospectively reconstructed OMG model trade | backfilled `4.28` | `4.54` at narrated 10:30 |
| DTS-20250626-T06 | July 3 609 calls; real companion trade | entered with T04; premium unavailable | exited near 01:09:41; premium unavailable |
| DTS-20250626-T07 | July 3 610 calls; published pick | average `4.15` at narrated 09:31 | `4.40` at narrated 10:26 |

## Entry and Exit Lessons

1. Freeze named-setup eligibility at the contemporaneous decision point.
2. Preserve profitable discretionary trades in a separate ledger rather than
   relabeling them after the outcome is known.
3. A close on resistance is not a close above resistance.
4. Reconcile intended and filled quantity before reporting trade economics.
5. Cross-day carry resolution requires immutable IDs; matching contract and
   approximate arithmetic is not enough.

## Contradictions and Process Risks

- The room correctly said no OMG close occurred, then later treated the 10:05
  discretionary trade as OMG.
- The reconstructed model trade was entered after the favorable move had
  already occurred.
- The second two-80 trade intended 15 contracts but later reported only ten
  fills.
- The prior-day 608-call sale at `5.50` was called a 24-cent gain, conflicting
  with the June 25 explicit `5.28` entry.
- The exact real 610-call exit was truncated in the transcript.

## Falsifiable Replay Hypotheses

1. Compare strict contemporaneous OMG labeling with retrospective relabeling.
2. Maintain separate outcome distributions for named signals and discretionary
   entries.
3. Require a close strictly beyond the boundary and test close-on-line cases
   separately.
4. Reconcile intended quantity, filled quantity, and model quantity before
   calculating returns.

## Ledger and Instrumentation Gaps

No visual chart verification, exact real quantities, immutable carry IDs,
complete real exit fills, broker orders, synchronized bars, option paths,
MFE/MAE, slippage, aggregate exposure, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, or risk-policy change
is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
