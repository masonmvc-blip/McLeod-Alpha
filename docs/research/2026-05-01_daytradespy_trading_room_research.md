# McLeod Alpha Research Report: 2026-05-01 Trading Room

## Scope and Evidence

External qualitative research based on the Day Trade SPY May 1, 2026 recording (1:10:44). Authenticated Vimeo captions were reviewed; this report retains synthesized evidence rather than source transcript content.

## Observations

- The session opened in a strong upside regime after overnight corporate and macro commentary. Price extended rapidly to new session highs and repeatedly exceeded nearby reference levels.
- The presenters tracked extension with measured moves, Fibonacci projections, moving-average pullbacks, and volume, while repeatedly warning that a strong move can still reverse after exhaustion.
- A pullback from the initial extension held a short-horizon moving average and retracement area before continuation. Later, a low-volume breakout attempt was explicitly treated as vulnerable to a head fake.
- The recording used options spread, delta, and contract volume to discuss whether a move was practically tradeable; some contracts had notably wide spreads during rapid movement.
- The session showed a recurring tension between a persistent bid and attempts to anticipate a reversal. The source itself emphasized waiting for observable break quality rather than relying on a reversal opinion.

## Research Implications

- Add `EXTENDED_IMPULSE` features for distance from opening range, measured-move extension, volume acceleration, and distance to the nearest retracement/support reference.
- Test `PULLBACK_HELD` only after a retracement touches or approaches a structural support area and then produces a close/reclaim with renewed volume.
- Label `LOW_VOLUME_BREAK` separately from accepted continuation and measure its rate of reversal, retracement depth, and time-to-failure.
- Include spread expansion and option liquidity in all extension/reversal replays; a directionally correct underlying move may still be non-executable at the contract level.

## Decision

No live entry, exit, stop, sizing, direction, or other trading-policy change is authorized by this external research. Candidate labels require replay, out-of-sample validation, and risk review.