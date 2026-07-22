# McLeod Alpha Research Note: July 17, 2026 Trading Room

## Scope and Evidence

Source recording: Day Trade SPY, "Trading Room Video Recording - July 17, 2026." The browser-visible Vimeo transcript was reviewed on July 22, 2026. This is external qualitative research only and does not alter McLeod Alpha execution or risk controls.

## Session Assessment

The room began indecisive near a pitchfork/pivot area, then identified a reversal from a multi-level support zone. The strongest transferable idea is confluence: a reversal candidate became more credible when a pivot, pitchfork level, and nearby moving-average structure aligned. The recording also contains an unsupported anti-stop opinion that should not influence system risk policy.

## Evidence Timeline

| Recording time | Observation | Research interpretation |
|---|---|---|
| 07:37-10:09 | The opening pattern was initially described as attractive but indecisive near a pitchfork line. | Pattern appearance alone was insufficient; the source waited for a resolution around structure. |
| 11:48-15:07 | Commentary identified a potential test of a pitchfork/pivot area and stated that a 50-EMA break should cancel the long idea. | This is a concrete invalidation concept: a setup requires a level-defined failure condition. |
| 27:21-31:15 | A 61.8% retracement, five-minute 50 EMA, pre-market resistance, and a potential double bottom were discussed while targets were adjusted closer. | Reversal confidence and target distance were both conditioned on nearby structure rather than direction alone. |
| 32:58-45:51 | The presenter described a support cluster containing a pitchfork level and pivot; price recovered, later formed a pennant, and calls were discussed after a 10-EMA wait. | A candidate `support_confluence_score` should combine independent levels, then require a confirmed reversal/reclaim before entry. |
| 51:12-52:19 | The recap stated a call entry around 5.91, a 6% target near 6.26, and an exit no later than 09:52. | Again, the room framed an opening trade around a predetermined short-duration reward objective. |
| 54:10-1:01:14 | Presenters argued from personal experience that trailing stops commonly fail and discouraged their use. | This is not evidence against McLeod Alpha's stop controls. It is anecdotal and conflicts with the system's tested risk framework; do not incorporate it without independent replay evidence. |

## Research Findings

1. **Support confluence is more useful than a single level.** The source repeatedly combined pivot, pitchfork, retracement, and moving-average references. A research feature should count independent, objectively defined support/resistance references rather than encode discretionary chart names.

2. **Level failure can be an entry invalidation feature.** The room's proposed 50-EMA cancellation supplies a testable shape: a bullish setup should be penalized or invalidated when price closes through its defining support with adverse momentum.

3. **Target compression remains important.** The presenter lowered a target when nearby resistance and the five-minute 50 EMA constrained upside. This supports testing a structural room-to-target gate.

4. **Retain stop policy as a protected risk control.** The recording's anti-trailing-stop claims are not a basis for changing live stops. Any stop-policy change remains subject to the existing replay, adverse-excursion, and certification process.

## Candidate Replay Experiments

1. Test a `support_confluence_score` composed of independently calculated pivot proximity, VWAP/EMA proximity, retracement zone proximity, and intraday range boundary proximity.
2. Compare confirmation requirements after a support-confluence reversal: immediate entry versus entry after a reclaim/hold above the relevant short-horizon EMA.
3. Evaluate whether structural room to resistance predicts target achievement and MFE better than the base directional score alone.

## Decision

The usable hypothesis is a measurable support-confluence and confirmation model. No live signal, stop, or trailing-stop behavior should change from this recording alone.