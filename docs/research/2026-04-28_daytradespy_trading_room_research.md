# McLeod Alpha Research Report: 2026-04-28 Trading Room

## Scope and Evidence

External qualitative research based on the Day Trade SPY April 28, 2026 recording (1:10:39). Authenticated Vimeo captions were reviewed; this report retains synthesized evidence rather than source transcript content.

## Observations

- The presenters described an overnight headline-driven decline, including AI-sector and energy-market commentary, followed by an opening recovery attempt.
- An early structural recovery was evaluated through an inverted-head-and-shoulders interpretation, moving-average reclaim, retracement levels, and a breakout above local resistance. The opening itself still invalidated some pre-open chart expectations.
- The recording repeatedly contrasted a one-minute reversal with more ambiguous five-minute structure. Several moves were characterized as range-bound or unresolved when moving averages remained compressed.
- Scheduled 10:00 data created a defined uncertainty window. The commentary focused on waiting for the observed price response rather than assuming the reported result would settle direction.
- Contract selection discussions covered delta, volume, open interest, spread, and the difference between a quoted level and a fillable outcome.

## Research Implications

- Add `GAP_RECOVERY_ATTEMPT` with features for overnight displacement, opening reversal depth, local structural reclaim, and whether the recovery survives the first post-open retest.
- Test `TIMEFRAME_CONFLICT` when one-minute momentum improves while five-minute structure remains range-bound or capped by moving-average resistance.
- Add `EVENT_WINDOW` around scheduled releases and measure whether pre-release structure persists, fails, or re-forms after the initial reaction.
- Treat contract liquidity fields as execution telemetry. Do not infer a deployable result from direction alone when spread, open interest, or displayed fill quality is weak.

## Decision

No live entry, exit, stop, sizing, direction, or other trading-policy change is authorized by this external research. Candidate labels require replay, out-of-sample validation, and risk review.